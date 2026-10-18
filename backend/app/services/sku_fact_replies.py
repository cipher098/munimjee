"""Fresh public SKU observations; no ORM authority cache, writer or provider call."""
import hashlib
import json
import re
from datetime import timedelta

from pydantic import ValidationError
from sqlalchemy import Text, and_, case, column, exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from app.config import settings
from app.models.catalogue_v1 import CatalogueProductMapping, CatalogueSKU
from app.models.checkout_v1 import CatalogueActivation
from app.models.commerce import Storefront
from app.models.identity import Business
from app.models.product import Product
from app.models.seller import Seller
from app.schemas.sku_fact_replies import ProductFacts, SKUFact


HANDOFF = "Our team will confirm the current options, price and availability for this product."
MAX_SKUS = 12


def enabled():
    # Missing shared rollout configuration must retain the current handoff.
    return getattr(settings, "V1_SKU_FACT_REPLIES_ENABLED", False) is True


async def is_activated(db, business_id, product_id):
    if not product_id:
        return False
    with db.no_autoflush:
        return bool(await db.scalar(select(CatalogueActivation.product_id).where(
            CatalogueActivation.business_id == business_id,
            CatalogueActivation.product_id == product_id)))


async def read_facts(db, business_id, product_id, *, instagram=None, reel=None):
    """One READ COMMITTED statement observes all gates and SKUs coherently.

    Scalar projections bypass retained ORM instances and never autoflush unrelated
    writes. No row locks are taken: the next stock writer must not wait on HTTP.
    Limit+1 fails closed rather than silently presenting a partial option set.
    """
    if not enabled() or not product_id:
        return None
    statement = select(Product.id, Product.name, CatalogueProductMapping.revision,
        CatalogueSKU.id.label("sku_id"), CatalogueSKU.options, CatalogueSKU.price_minor,
        CatalogueSKU.currency, CatalogueSKU.stock_available,
        func.clock_timestamp().label("observed_at")).select_from(Product).join(
        Seller, Seller.id == Product.seller_id).join(Business, Business.id == Product.seller_id).join(
        Storefront, Storefront.seller_id == Product.seller_id).join(CatalogueActivation,
        (CatalogueActivation.business_id == Product.seller_id) & (CatalogueActivation.product_id == Product.id)).join(
        CatalogueProductMapping, (CatalogueProductMapping.business_id == Product.seller_id) &
        (CatalogueProductMapping.product_id == Product.id)).join(CatalogueSKU,
        (CatalogueSKU.business_id == Product.seller_id) & (CatalogueSKU.product_id == Product.id)).where(
        Product.seller_id == business_id, Product.id == product_id, Product.active.is_(True),
        Seller.is_active.is_(True), Business.is_active.is_(True), Storefront.published.is_(True),
        CatalogueProductMapping.state == "reviewed", CatalogueSKU.active.is_(True),
        CatalogueProductMapping.revision >= CatalogueActivation.reviewed_revision,
    ).order_by(CatalogueSKU.id).limit(MAX_SKUS + 1)
    if instagram is not None:
        statement = statement.where(*instagram_filters(business_id, product_id, **instagram))
    if reel is not None:
        exact = reel_candidates(business_id, **reel).cte("exact_reel_products")
        statement = statement.where(Product.id.in_(select(exact.c.id)),
            select(func.count()).select_from(exact).scalar_subquery() == 1)
    with db.no_autoflush:
        rows = (await db.execute(statement)).mappings().all()
    if not rows or len(rows) > MAX_SKUS or not enabled():
        return None
    try:
        skus = tuple(SKUFact(sku_id=row["sku_id"], options=row["options"], price_minor=row["price_minor"],
            currency=row["currency"], stock_available=row["stock_available"]) for row in rows)
        if len({json.dumps(sku.options, sort_keys=True) for sku in skus}) != len(skus):
            return None
        public = dict(business_id=business_id, product_id=rows[0]["id"], product_name=rows[0]["name"],
            mapping_revision=rows[0]["revision"], skus=skus)
        digest = hashlib.sha256(json.dumps({**public, "skus":[sku.model_dump(mode="json") for sku in skus]},
            sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()
        facts = ProductFacts(**public, observed_at=rows[0]["observed_at"], fact_hash=digest)
        return facts if len(render(facts)) <= 3500 else None
    except (TypeError, ValueError, ValidationError):
        return None


def render(facts):
    lines = [f"Current catalogue: {facts.product_name}."]
    for sku in facts.skus:
        options = "; ".join(f"{key}: {value}" for key, value in sorted(sku.options.items())) or "Standard option"
        price = f"₹{sku.price_minor // 100:,}.{sku.price_minor % 100:02d}"
        stock = ("availability untracked; please confirm with our team" if sku.stock_available is None else
                 "recorded out of stock" if sku.stock_available == 0 else f"recorded available: {sku.stock_available}")
        lines.append(f"• {options} — {price}; {stock}.")
    lines.append("Availability is a current catalogue observation, not a reservation. Please confirm your preferred option with our team.")
    return "\n".join(lines)


# Deliberately small factual vocabulary; other requests retain human handling.
_FACT_WORDS = frozenset("price prices cost costs stock available availability option options variant variants colour colours color colors size sizes material materials what which is are the this that it its for of and or please pls plz hi hello hey show tell me you your in have hai kya ka ki ke kitna kitne rate rates details current catalogue product rupees rs".split())


def factual_request(text):
    if not isinstance(text, str) or len(text) > 500:
        return False
    words = re.findall(r"[^\W\d_]+", text.casefold(), re.UNICODE)
    requested = {"price","prices","cost","costs","stock","available","availability","option","options",
        "variant","variants","colour","colours","color","colors","size","sizes","material","materials","rate","rates","details","kitna","kitne"}
    return bool(requested.intersection(words)) and all(word in _FACT_WORDS for word in words) and not re.search(r"\d|https?://", text)


def reel_question(text):
    from app.services.whatsapp_context import URL_RE, instagram_references
    # The trusted exact reference is checked separately; a bare link requests
    # these public facts, while any remaining transactional text still hands off.
    question = URL_RE.sub(lambda match: "" if instagram_references(match.group()) else match.group(), text or "").strip()
    return "[customer sent media]" if not question else question


def reel_candidates(business_id, *, reel_url="", media_id=None):
    """Exact allowlisted URL/numeric mapping predicate reusable at final read.

    Host/scheme matching ignores ASCII case; shortcode/path matching does not.
    SQL expansion selects no legacy/private facts and never chooses first-hit.
    """
    from app.services.whatsapp_context import instagram_references
    refs = instagram_references(reel_url)
    if len(refs) > 1:
        return select(Product.id).where(literal(False))
    codes = {ref["shortcode"] for ref in refs}
    numeric = media_id if isinstance(media_id, str) and re.fullmatch(r"[0-9]{1,64}", media_id) else None
    links = func.jsonb_array_elements(case((func.jsonb_typeof(Product.reel_urls) == "array", Product.reel_urls),
        else_=literal([], type_=JSONB))).table_valued(column("value", JSONB)).alias("linked_reel")
    value = links.c.value.op("#>>", return_type=Text)(literal([], type_=ARRAY(Text)))
    # PostgreSQL's global case-insensitive flag would incorrectly collapse two
    # distinct shortcodes. Restrict case folding to the scheme and hostname.
    prefix = r"^[hH][tT][tT][pP][sS]?://([wW][wW][wW]\.|[mM]\.)?[iI][nN][sS][tT][aA][gG][rR][aA][mM]\.[cC][oO][mM]/"
    predicates = [value.op("~")(
        prefix + r"(reel|reels|p|tv)/" + re.escape(code) + r"/?([?#][^\s]*)?$") for code in sorted(codes)]
    if numeric:
        predicates.append(value == numeric)
    matches = exists(select(1).select_from(links).where(and_(func.jsonb_typeof(links.c.value) == "string",
        or_(*predicates)))).correlate(Product) if predicates else literal(False)
    return select(Product.id).where(Product.seller_id == business_id, Product.active.is_(True), matches)


async def exact_reel_products(db, business_id, *, reel_url="", media_id=None):
    from app.services.whatsapp_context import instagram_references
    if len(instagram_references(reel_url)) > 1:
        return None
    with db.no_autoflush:
        rows = (await db.scalars(reel_candidates(business_id, reel_url=reel_url, media_id=media_id)
            .order_by(Product.id).limit(101))).all()
    if len(rows) > 100:
        return None
    return tuple(rows)


def instagram_filters(business_id, product_id, *, conversation_id, customer_id, token, page_id):
    """Fresh sender gates in the SAME statement as catalogue facts.

    Only current durable processing can emit this new behavior. Resume/nudges
    without an owned signed-source turn remain the incumbent human handoff.
    """
    from app.models.channel_operator import ChannelConnectionState
    from app.models.commerce_safeguards import PaymentReview
    from app.models.conversation import Conversation
    from app.models.conversation_product import ConversationProduct
    from app.models.instagram_ingress import InstagramIngress
    from app.models.manual_action import ManualAction
    from app.services.instagram_ingress import UNKNOWN_EFFECT_ERRORS
    current = func.clock_timestamp()
    thread = (InstagramIngress.seller_id == business_id, InstagramIngress.customer_id == customer_id)
    return (
        literal(bool(token and page_id)),
        Seller.instagram_token == token, Seller.fb_page_id == page_id,
        or_(Seller.instagram_token_expires_at.is_(None), Seller.instagram_token_expires_at > current),
        exists(select(Conversation.id).where(Conversation.id == conversation_id,
            Conversation.seller_id == business_id, Conversation.customer_instagram_id == customer_id,
            Conversation.product_id == product_id,
            or_(Conversation.last_seller_manual_reply_at.is_(None),
                Conversation.last_seller_manual_reply_at < current - timedelta(minutes=settings.BOT_AUTO_RESUME_AFTER_MINUTES)),
            or_(Conversation.disengage_paused_until.is_(None), Conversation.disengage_paused_until < current))),
        ~exists(select(ChannelConnectionState.business_id).where(ChannelConnectionState.business_id == business_id,
            ChannelConnectionState.channel == "instagram", ChannelConnectionState.automation_enabled.is_(False))),
        exists(select(InstagramIngress.id).where(*thread, InstagramIngress.status == "processing",
            InstagramIngress.account_id == Seller.instagram_page_id,
            InstagramIngress.occurred_at >= current - timedelta(hours=24),
            InstagramIngress.occurred_at <= current + timedelta(minutes=5))),
        ~exists(select(InstagramIngress.id).where(*thread, InstagramIngress.status == "error",
            InstagramIngress.error_code.in_(UNKNOWN_EFFECT_ERRORS))),
        ~exists(select(ManualAction.id).where(ManualAction.conversation_id == conversation_id,
            ManualAction.seller_id == business_id, ManualAction.status == "open")),
        ~exists(select(PaymentReview.id).where(PaymentReview.conversation_id == conversation_id,
            PaymentReview.seller_id == business_id, PaymentReview.status == "pending")),
        # Do not restart price discovery inside an already agreed/payment cycle.
        ~exists(select(ConversationProduct.id).where(ConversationProduct.conversation_id == conversation_id,
            or_(ConversationProduct.agreed_price.isnot(None), ConversationProduct.state.in_(
                ("awaiting_payment", "verifying", "manual_review"))))),
    )
