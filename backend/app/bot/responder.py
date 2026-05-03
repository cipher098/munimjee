"""
Hybrid AI response generation.
  Step 1 — Claude decides WHAT to do (action + price).
  Step 2 — Sarvam generates reply in seller's Hinglish style.
  Fallback — Claude generates reply if Sarvam fails.
"""
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.conversation_product import ConversationProduct
from app.models.product import Product
from app.models.seller import Seller

logger = logging.getLogger(__name__)


def _clean_reply(text: str) -> str:
    """Remove characters that should never appear in customer-facing messages."""
    return text.replace("—", "").strip()


DEFAULT_PERSONA = {
    "greeting_style": "Haan ji, kya chahiye?",
    "negotiation_firmness": "medium",
    "closing_phrases": ["Done ho gaya", "Pakka"],
    "common_expressions": ["yaar", "theek hai"],
    "hindi_english_ratio": "60% Hindi 40% English",
    "emoji_usage": "light",
    "response_length": "short",
    "tone": "casual",
    "sample_responses": {
        "greeting": "Haan ji! Kya chahiye aapko? 😊",
        "price_rejection": "Yaar itna kam nahi hoga, last price hai ye",
        "deal_accepted": "Done! Payment kar do jaldi",
        "payment_request": "Yaar payment kar do, UPI hai — details bhej raha hoon",
        "dispatched": "Dispatch ho gaya aapka order, tracking bhejta hoon"
    }
}


async def generate_bot_reply(
    conversation: Conversation,
    customer_message: str,
    seller: Seller,
    db: AsyncSession,
    conv_product: ConversationProduct | None = None,
) -> tuple[str | None, str | None, dict[str, Any]]:
    """
    Returns (reply_text, new_state, extra_dict).
    extra_dict may contain: agreed_price, negotiation_round, product_id.
    """
    product: Product | None = None
    if conversation.product_id:
        result = await db.execute(select(Product).where(Product.id == conversation.product_id))
        product = result.scalar_one_or_none()

    # Always load full catalog so Claude can switch products mid-conversation
    result = await db.execute(
        select(Product).where(Product.seller_id == seller.id, Product.active == True)
    )
    all_products = result.scalars().all()
    products_list = [
        {"id": str(p.id), "name": p.name, "listed_price_paise": p.listed_price}
        for p in all_products
    ]

    from app.integrations.claude import ClaudeClient
    from app.integrations.sarvam import SarvamClient
    from app.models.category_tag import CategoryTag
    from app.models.product_category import ProductCategory
    from app.models.product_tag_value import ProductTagValue
    from app.models.seller_alert import SellerAlert

    claude = ClaudeClient()
    sarvam = SarvamClient()

    # Resolve price state: conv_product is the source of truth.
    # When no conv_product exists yet (no product identified), default to zero/none.
    if conv_product is not None:
        effective_negotiation_round = conv_product.negotiation_round
        effective_last_counter_price = conv_product.last_counter_price
        price_state_source = "conv_product"
    else:
        effective_negotiation_round = 0
        effective_last_counter_price = None
        price_state_source = "none"

    # Tag lookup — load category tags + values for the current product
    product_tag_values: dict[str, str] = {}   # display_name → value, for known specs
    category_tags: list[dict] = []            # all tag definitions for this category

    if product and product.category_id:
        try:
            cat_result = await db.execute(
                select(CategoryTag).where(CategoryTag.category_id == product.category_id)
            )
            db_tags = cat_result.scalars().all()
            category_tags = [
                {
                    "name": t.name,
                    "display_name": t.display_name,
                    "value_type": t.value_type,
                    "allowed_values": t.allowed_values,
                }
                for t in db_tags
            ]
            val_result = await db.execute(
                select(ProductTagValue).where(ProductTagValue.product_id == product.id)
            )
            tag_id_to_tag = {t.id: t for t in db_tags}
            for tv in val_result.scalars().all():
                tag = tag_id_to_tag.get(tv.tag_id)
                if tag:
                    product_tag_values[tag.display_name] = tv.value
        except Exception as exc:
            logger.warning("Tag lookup failed: %s", exc)

    # If product has a category and the customer seems to be asking a feature question,
    # check if we have the answer or need to pause and notify the seller.
    if product and product.category_id and category_tags:
        try:
            fq = await claude.extract_feature_query(customer_message, category_tags)

            # ── TAG DECISION LOG ──────────────────────────────────────────────
            logger.info(
                "\n┌─────────────────────────────────────────\n"
                "│ TAG DECISION\n"
                "│ CUSTOMER MSG  : %s\n"
                "│ IS FEATURE Q  : %s\n"
                "│ MATCHED TAG   : %s\n"
                "│ NEW TAG NAME  : %s  |  DISPLAY: %s\n"
                "│ NEW TAG TYPE  : %s  |  OPTIONS: %s\n"
                "└─────────────────────────────────────────",
                customer_message,
                fq.get("is_feature_question"),
                fq.get("matched_tag_name") or "—",
                fq.get("new_tag_name") or "—",
                fq.get("new_tag_display_name") or "—",
                fq.get("new_tag_value_type") or "—",
                fq.get("new_tag_allowed_values") or "—",
            )

            if fq.get("is_feature_question"):
                matched_name = fq.get("matched_tag_name")
                new_name = fq.get("new_tag_name")
                new_display = fq.get("new_tag_display_name") or new_name

                # Find the matched or newly-needed tag
                matched_tag_obj = None
                if matched_name:
                    tag_result = await db.execute(
                        select(CategoryTag).where(
                            CategoryTag.category_id == product.category_id,
                            CategoryTag.name == matched_name,
                        )
                    )
                    matched_tag_obj = tag_result.scalar_one_or_none()
                    logger.info(
                        "TAG LOOKUP: matched existing tag %r → found=%s",
                        matched_name, matched_tag_obj is not None,
                    )
                elif new_name:
                    # Auto-create tag for this category using Claude's suggested type/values
                    new_value_type = fq.get("new_tag_value_type") or "text"
                    new_allowed = fq.get("new_tag_allowed_values") or None
                    if new_value_type not in ("enum", "text", "number"):
                        logger.warning(
                            "TAG TYPE OVERRIDE: Claude returned %r for tag %r — falling back to 'text'",
                            new_value_type, new_name,
                        )
                        new_value_type = "text"
                    matched_tag_obj = CategoryTag(
                        category_id=product.category_id,
                        name=new_name,
                        display_name=new_display or new_name,
                        value_type=new_value_type,
                        allowed_values=new_allowed,
                    )
                    db.add(matched_tag_obj)
                    await db.flush()
                    logger.info(
                        "TAG CREATED: %r (display=%r, type=%s, options=%s) for category %s, product %r",
                        new_name, new_display, new_value_type, new_allowed,
                        product.category_id, product.name,
                    )

                if matched_tag_obj:
                    has_value = matched_tag_obj.display_name in product_tag_values
                    logger.info(
                        "TAG VALUE CHECK: tag=%r  has_value=%s  known_values=%s",
                        matched_tag_obj.name, has_value,
                        list(product_tag_values.keys()),
                    )
                    if not has_value:
                        # Pause this product's state machine, alert seller
                        if conv_product is not None:
                            conv_product.state = "waiting_for_tag"
                            conv_product.pending_tag_id = matched_tag_obj.id
                        await db.flush()

                        # Create alert only if one doesn't already exist
                        existing_alert = await db.execute(
                            select(SellerAlert).where(
                                SellerAlert.product_id == product.id,
                                SellerAlert.tag_id == matched_tag_obj.id,
                                SellerAlert.resolved_at.is_(None),
                            )
                        )
                        alert_exists = existing_alert.scalar_one_or_none() is not None
                        if not alert_exists:
                            db.add(SellerAlert(
                                seller_id=seller.id,
                                product_id=product.id,
                                tag_id=matched_tag_obj.id,
                                conversation_id=conversation.id,
                            ))
                        await db.flush()
                        logger.info(
                            "SELLER ALERT: tag=%r  product=%r  alert_already_existed=%s  "
                            "→ conversation %s paused (waiting_for_tag)",
                            matched_tag_obj.name, product.name, alert_exists, conversation.id,
                        )
                        return None, "waiting_for_tag", {}
        except Exception as exc:
            logger.warning("Feature query check failed: %s — proceeding normally", exc)

    # Split other ConversationProducts into inquiry (undecided, with prices) vs all active
    _INACTIVE_STATES = {"not_interested", "payment_confirmed", "failed", "dispatched_notified", "purchased"}
    _other_cp_result = await db.execute(
        select(ConversationProduct, Product)
        .join(Product, ConversationProduct.product_id == Product.id)
        .where(
            ConversationProduct.conversation_id == conversation.id,
            ConversationProduct.product_id != conversation.product_id if conversation.product_id else True,
            ~ConversationProduct.state.in_(_INACTIVE_STATES),
        )
    )
    _other_rows = _other_cp_result.all()
    other_inquiry_products = [
        {
            "id": str(p.id),
            "name": p.name,
            "listed_price_rupees": p.listed_price // 100,
            "floor_price_rupees": p.floor_price // 100 if p.floor_price else p.listed_price // 100,
            "state": cp.state,
        }
        for cp, p in _other_rows
        if cp.state == "product_inquiry"
    ]
    other_active_products = [
        {"id": str(p.id), "name": p.name, "state": cp.state}
        for cp, p in _other_rows
    ]

    # Step 1: Claude decides action
    effective_state = conv_product.state if conv_product is not None else "greeting"
    decision = await claude.decide({
        "state": effective_state,
        "customer_message": customer_message,
        "negotiation_round": effective_negotiation_round,
        "listed_price": product.listed_price if product else None,
        "floor_price": product.floor_price if product else None,   # never forwarded to customer
        "last_counter_price": effective_last_counter_price,
        "message_history": (conversation.messages or [])[-10:],
        "available_products": products_list,
        "other_inquiry_products": other_inquiry_products,
        "bundle_pitched": conv_product.bundle_pitched if conv_product is not None else False,
    })

    logger.info(
        "Decision context — last_counter=₹%s (src:%s) floor=₹%s round=%s",
        effective_last_counter_price // 100 if effective_last_counter_price else "none",
        price_state_source,
        product.floor_price // 100 if product else "none",
        effective_negotiation_round,
    )

    # Safety override — if product is known, clarify is never appropriate
    if decision.get("action") == "clarify" and product:
        logger.warning(
            "Claude chose 'clarify' with known product %r — overriding to engage", product.name
        )
        decision["action"] = "engage"

    new_state, extra = _derive_state_from_decision(
        decision, conversation, product,
        effective_negotiation_round=effective_negotiation_round,
        effective_last_counter_price=effective_last_counter_price,
        inquiry_products=other_inquiry_products,
    )

    # Compute code-enforced price breakdowns — used for show_multi_price and
    # as a safe reference when customer explicitly asks for per-product breakdown.
    multi_price_breakdown: str = ""
    bundle_breakdown: str = ""

    # show_multi_price: prices come entirely from code, never from LLM.
    if decision.get("action") == "show_multi_price" and extra.get("product_ids"):
        parts = []
        for pid in extra["product_ids"]:
            p_res = await db.execute(select(Product).where(Product.id == pid))
            p = p_res.scalar_one_or_none()
            if not p:
                continue
            cp_res = await db.execute(
                select(ConversationProduct).where(
                    ConversationProduct.conversation_id == conversation.id,
                    ConversationProduct.product_id == pid,
                )
            )
            cp = cp_res.scalar_one_or_none()
            raw = (cp.last_counter_price if cp and cp.last_counter_price else p.listed_price) or p.listed_price
            display_price = max(raw, p.floor_price)
            parts.append(f"{p.name}: ₹{display_price // 100}")
            logger.info("show_multi_price code-computed: %s = ₹%d (floor=₹%d)",
                        p.name, display_price // 100, p.floor_price // 100)
        multi_price_breakdown = " | ".join(parts)

    # Bundle breakdown: when counter/accept covers multiple products, pre-compute a
    # floor-safe per-product split so the reply model never has to do this math itself.
    # Formula: each product gets its floor, surplus is split proportionally by listed price.
    if other_inquiry_products and decision.get("action") in ("counter", "accept", "bulk_discount"):
        total_paise = decision.get("price") or 0
        bundle_items = []
        if product:
            bundle_items.append({
                "name": product.name,
                "floor": product.floor_price or 0,
                "listed": product.listed_price or 0,
            })
        for p in other_inquiry_products:
            bundle_items.append({
                "name": p["name"],
                "floor": int(p.get("floor_price_rupees", 0)) * 100,
                "listed": int(p.get("listed_price_rupees", 0)) * 100,
            })
        sum_floors = sum(i["floor"] for i in bundle_items)
        surplus = max(0, total_paise - sum_floors)
        sum_listed = sum(i["listed"] for i in bundle_items) or 1
        parts = []
        for i in bundle_items:
            allocated = i["floor"] + int(surplus * (i["listed"] / sum_listed))
            # Final safety clamp — should never be needed but belt-and-suspenders
            allocated = max(allocated, i["floor"])
            parts.append(f"{i['name']}: ₹{allocated // 100}")
        bundle_total = total_paise // 100
        bundle_breakdown = ", ".join(parts) + f" (total: ₹{bundle_total})"
        logger.info("Bundle breakdown computed: %s", bundle_breakdown)

    # If Claude switched to a different product, reload it so reply text uses the correct product
    switched_product_id = decision.get("product_id")
    if switched_product_id and str(switched_product_id) != str(conversation.product_id):
        result = await db.execute(select(Product).where(Product.id == switched_product_id))
        switched = result.scalar_one_or_none()
        if switched:
            product = switched
            logger.info("Product switched to %r for reply generation", product.name)
            # Reset pricing to new product's negotiation state — old product's counter price must not leak
            new_cp_res = await db.execute(
                select(ConversationProduct).where(
                    ConversationProduct.conversation_id == conversation.id,
                    ConversationProduct.product_id == switched_product_id,
                )
            )
            new_cp = new_cp_res.scalar_one_or_none()
            effective_last_counter_price = new_cp.last_counter_price if new_cp else None
            price_state_source = "conv_product" if new_cp else "none"

    persona = seller.persona or DEFAULT_PERSONA

    all_photo_count = (1 if product and product.photo_url else 0) + (len(product.photo_urls) if product and product.photo_urls else 0)

    from app.utils.gender import guess_gender, address_term as _address_term
    customer_gender = conversation.customer_gender or guess_gender(conversation.customer_name or "")
    customer_address_term = _address_term(customer_gender)

    reply_context = {
        "decision": decision,
        "persona": persona,
        "product_name": product.name if product else "the product",
        "product_description": product.description if product else None,
        "product_tag_values": product_tag_values,
        "listed_price_rupees": product.listed_price // 100 if product else None,
        "floor_price_rupees": product.floor_price // 100 if product else None,
        "warranty_months": product.warranty_months if product else None,
        "stock_quantity": product.stock_quantity if product else None,
        "last_counter_price": effective_last_counter_price,
        "bulk_quantity": decision.get("bulk_quantity"),
        "customer_message": customer_message,
        "policies": seller.policies or {},
        "available_products": products_list,
        "message_history": (conversation.messages or [])[-10:],
        "total_photos": all_photo_count,
        "address_term": customer_address_term,
        "other_active_products": other_active_products,
        "other_inquiry_products": other_inquiry_products,
        "multi_price_breakdown": multi_price_breakdown,
        "bundle_breakdown": bundle_breakdown,
        "inquiry_floor_total_rupees": sum(
            int(p.get("floor_price_rupees", 0)) for p in other_inquiry_products
        ) if other_inquiry_products else 0,
    }

    # Step 2: Sarvam generates the actual message text
    try:
        reply = await sarvam.generate_reply(reply_context)
    except Exception as exc:
        logger.warning("Sarvam failed (%s), falling back to Claude for reply", exc)
        reply = await claude.generate_reply(reply_context)

    price_paise = decision.get("price")
    price_str = f"₹{price_paise // 100}" if price_paise else "—"
    counter_str = (
        f"₹{effective_last_counter_price // 100} ({price_state_source})"
        if effective_last_counter_price
        else "none"
    )
    rejected_ids_str = ", ".join(str(r) for r in (decision.get("rejected_product_ids") or [])) or "—"
    logger.info(
        "\n"
        "┌─────────────────────────────────────────\n"
        "│ CUSTOMER    : %s\n"
        "│ STATE       : %s  →  %s\n"
        "│ PRODUCT     : %s\n"
        "│ ACTION      : %s  |  PRICE: %s  |  INTENT: %s  |  ROUND: %s\n"
        "│ LAST COUNTER: %s\n"
        "│ REASON      : %s\n"
        "│ REJECTED IDS: %s\n"
        "│ BOT REPLY   : %s\n"
        "└─────────────────────────────────────────",
        customer_message,
        effective_state, new_state or "(no change)",
        product.name if product else "none",
        decision.get("action"), price_str, decision.get("customer_intent"), effective_negotiation_round,
        counter_str,
        decision.get("reason", ""),
        rejected_ids_str,
        reply,
    )

    if reply:
        reply = _clean_reply(reply)
    return reply, new_state, extra


def _derive_state_from_decision(
    decision: dict,
    conversation: Conversation,
    product: Product | None,
    effective_negotiation_round: int = 0,
    effective_last_counter_price: int | None = None,
    inquiry_products: list[dict] | None = None,
) -> tuple[str | None, dict]:
    """Maps Claude's action to a state transition and extra data.

    effective_negotiation_round and effective_last_counter_price are the source-of-truth
    values (from conv_product when available, otherwise from conversation columns).
    inquiry_products: other_inquiry_products list with floor_price_rupees per item.
    """
    action = decision.get("action", "")
    floor_price = product.floor_price if product else None
    extra: dict[str, Any] = {}

    # Always forward rejected_product_ids regardless of action chosen
    if decision.get("rejected_product_ids"):
        extra["rejected_product_ids"] = list(decision["rejected_product_ids"])

    # Compute inquiry floor total (paise) — sum of all inquiry product floors.
    # Used to enforce minimum bundle price when the offer covers multiple products.
    inquiry_floor_paise = sum(
        int(p.get("floor_price_rupees", 0)) * 100
        for p in (inquiry_products or [])
    )

    def _clamp_to_floors(price: int) -> int:
        """Raise price to the highest applicable floor: single-product or bundle."""
        # Single-product floor
        if floor_price and price < floor_price:
            logger.warning(
                "FLOOR GUARD: price %d below current product floor %d — clamping",
                price, floor_price,
            )
            price = floor_price
        # Bundle floor: when price is larger than single product's listed price,
        # it is covering inquiry products too — enforce sum-of-floors.
        if inquiry_floor_paise and price > 0:
            bundle_floor = (floor_price or 0) + inquiry_floor_paise
            if price < bundle_floor and price > (floor_price or 0):
                logger.warning(
                    "FLOOR GUARD: bundle price %d below sum-of-floors %d — clamping",
                    price, bundle_floor,
                )
                price = bundle_floor
        return price

    if action == "accept":
        price = decision.get("price") or 0
        price = _clamp_to_floors(price)
        decision["price"] = price
        # If clamping pushed us above what customer offered, revert to hold_firm
        original_price = decision.get("price", 0)
        if floor_price and original_price and original_price < floor_price:
            logger.warning(
                "FLOOR GUARD: accept %d below floor %d — overriding to hold_firm",
                original_price, floor_price,
            )
            action = "hold_firm"
            decision["action"] = "hold_firm"
        else:
            extra["agreed_price"] = price
            extra["last_counter_price"] = price  # lock in — can never go lower if renegotiated
            return "awaiting_payment", extra

    if action == "counter":
        price = decision.get("price") or 0
        listed_price = product.listed_price if product else None
        # Hard block — fixed-price product (floor == listed): never counter, fall through to hold_firm
        if floor_price and listed_price and floor_price >= listed_price:
            logger.warning(
                "FLOOR GUARD: counter on fixed-price product (listed=%d floor=%d) — overriding to hold_firm",
                listed_price, floor_price,
            )
            action = "hold_firm"
            decision["action"] = "hold_firm"
            decision["price"] = None
        else:
            price = _clamp_to_floors(price)
            decision["price"] = price
            # Hard clamp — counter price can never go HIGHER than last counter
            if price and effective_last_counter_price and price > effective_last_counter_price:
                logger.warning(
                    "FLOOR GUARD: counter %d higher than previous offer %d — clamping down",
                    price, effective_last_counter_price,
                )
                price = effective_last_counter_price
                decision["price"] = price
            if price:
                extra["last_counter_price"] = price
            extra["negotiation_round"] = effective_negotiation_round + 1
            return "negotiating", extra

    if action == "hold_firm":
        extra["negotiation_round"] = effective_negotiation_round + 1
        return "negotiating", extra

    if action == "bulk_discount":
        price = decision.get("price") or 0
        price = _clamp_to_floors(price)
        decision["price"] = price
        extra["agreed_price"] = price
        extra["last_counter_price"] = price  # lock in — can never go lower if renegotiated
        extra["bulk_quantity"] = decision.get("bulk_quantity")
        return "awaiting_payment", extra

    if action == "request_payment":
        return "awaiting_payment", extra

    if action == "escalate":
        return "manual_review", extra

    if action == "not_interested":
        rejected = list(decision.get("rejected_product_ids") or [])
        decision_product_id = decision.get("product_id")
        current_product_id = str(product.id) if product else None

        if decision_product_id and current_product_id and str(decision_product_id) != current_product_id:
            # Claude identified a DIFFERENT product as rejected, not the active one.
            # Move it to rejected_product_ids only — do not mark the current product.
            if str(decision_product_id) not in [str(r) for r in rejected]:
                rejected.append(str(decision_product_id))
            extra["rejected_product_ids"] = rejected
            logger.info(
                "not_interested on non-active product %s → routing to rejected_product_ids only",
                decision_product_id,
            )
            return None, extra

        extra["rejected_product_ids"] = rejected
        return "not_interested", extra

    if action == "bundle_pitch":
        extra["bundle_pitch"] = True
        return None, extra  # no state change

    if action == "show_multi_price":
        extra["product_ids"] = decision.get("product_ids") or []
        return None, extra  # no state change

    if action == "show_product":
        product_id = decision.get("product_id")
        if product_id:
            extra["product_id"] = product_id
        elif product:
            extra["product_id"] = product.id
        extra["send_image"] = True  # always send product image for show_product
        return "product_inquiry", extra

    return None, extra


async def send_manual_verification_ping(
    conversation: Conversation,
    seller: Seller,
    image_url: str,
    db: AsyncSession,
    conv_product=None,
) -> None:
    """Level 5: send WhatsApp ping to seller for manual payment confirmation."""
    from app.integrations.instagram import InstagramClient

    # Notify customer we're verifying
    client = InstagramClient(seller.instagram_token, seller.fb_page_id)
    await client.send_message(
        conversation.customer_instagram_id,
        "Ek second — payment verify kar rahe hain 🔍",
    )

    if not seller.whatsapp_number:
        logger.warning(
            "Seller %s has no WhatsApp number — cannot send manual verification ping",
            seller.id,
        )
        if conv_product is not None:
            conv_product.state = "manual_review"
        await db.flush()
        return

    agreed_price = conv_product.agreed_price if conv_product is not None else None
    amount_rupees = (agreed_price or 0) // 100

    ping_text = (
        f"💰 Payment screenshot received!\n"
        f"Amount: ₹{amount_rupees}\n"
        f"Customer: {conversation.customer_instagram_id}\n"
        f"Screenshot: {image_url}\n\n"
        f"Reply *1* to confirm, *0* to reject."
    )

    try:
        from app.integrations.whatsapp import WhatsAppClient
        wa = WhatsAppClient()
        await wa.send_message(seller.whatsapp_number, ping_text)
    except Exception as exc:
        logger.error("Failed to send WhatsApp ping to seller %s: %s", seller.id, exc)

    if conv_product is not None:
        conv_product.state = "manual_review"
    await db.flush()
