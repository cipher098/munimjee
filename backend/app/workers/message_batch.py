"""
Celery task: process a batch of messages from the same customer that arrived within
a 15-second debounce window.  Each incoming webhook event is queued in Redis;
a delayed task fires after 15 s of silence and processes them all, sending exactly
one bot reply.
"""
from app.workers.async_runner import run_async
from datetime import datetime, timedelta, timezone
import json
import logging
import re

from sqlalchemy import select
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

BATCH_WINDOW_SECONDS = 0
_BATCH_KEY_PREFIX = "msg_batch:"
_TASK_KEY_PREFIX = "msg_batch_task:"


def is_bot_paused_for_manual_takeover(
    last_seller_manual_reply_at: datetime | None,
    window_minutes: int,
    now: datetime | None = None,
) -> bool:
    """True when a recent seller manual reply puts the bot in takeover mode."""
    if last_seller_manual_reply_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    return (current - last_seller_manual_reply_at) < timedelta(minutes=window_minutes)


def extract_customer_text_entries(events: list[dict], now: datetime | None = None) -> list[dict]:
    """Turn the worker's queued text events into JSONB rows for conversation.messages.

    Used to preserve customer messages during a seller takeover pause — the
    reply path is skipped, but we still want the bot to see what was said
    once it resumes.
    """
    ts = (now or datetime.now(timezone.utc)).isoformat()
    out: list[dict] = []
    for event in events:
        if event.get("type") != "text":
            continue
        text = event.get("text")
        if not text:
            continue
        entry: dict = {"role": "customer", "content": text, "timestamp": ts}
        if event.get("mid"):
            entry["mid"] = event["mid"]
        out.append(entry)
    return out


def is_bot_paused_for_disengage(
    disengage_paused_until: datetime | None,
    now: datetime | None = None,
) -> bool:
    """True when the customer-disengagement quiet window has not yet expired."""
    if disengage_paused_until is None:
        return False
    current = now or datetime.now(timezone.utc)
    return current < disengage_paused_until


# Customer messages containing any of these substrings (case-insensitive) lift
# the disengage pause — they signal renewed buying intent. Intentionally broad:
# a false positive costs one extra ack, a false negative loses a sale.
# Note: words that commonly appear in negations ("chahiye" → "nahi chahiye",
# "milega" → "nahi milega") are deliberately OUT — too easy to invert meaning.
_REENGAGE_KEYWORDS = (
    "price", "kitne", "kitna", "dam", "rate",
    "le lunga", "le lungi", "lelo", "le do", "dedo",
    "fix karo", "fix kar do", "confirm",
    "yes", "haan", "accept",
    "order", "buy", "purchase",
    "lunga", "lungi", "leta hoon", "leti hoon",
)
_REENGAGE_NUMBER_RE = re.compile(r"\d+")
# If the customer's text contains any of these negation markers we ignore
# keyword/number matches — likely a polite refusal ("nahi chahiye, 0 interest").
_NEGATION_MARKERS = ("nahi", "nahin", "no thanks", "not interested", "mat ")


def is_reengagement_signal(text: str | None) -> bool:
    """True when the customer's text shows buying intent and the disengage
    pause should drop. Keyword / digit / question-mark detection, gated by
    a negation check so "nahi chahiye" stays muted."""
    if not text:
        return False
    lowered = text.lower()
    if any(neg in lowered for neg in _NEGATION_MARKERS):
        return False
    if any(kw in lowered for kw in _REENGAGE_KEYWORDS):
        return True
    if _REENGAGE_NUMBER_RE.search(lowered):
        return True
    if "?" in text:
        return True
    return False


def unanswered_customer_messages(messages: list[dict] | None) -> list[dict]:
    """Return the trailing run of customer turns from conversation history.

    Walks backwards until we hit a `bot` or `seller_manual` turn — those are
    brand-side messages, meaning anything before them has already been
    addressed. Returns the customer turns in chronological order.

    Empty when the most recent entry is brand-side (bot or seller_manual) —
    that's the signal nothing is unanswered, so the wake-up task should no-op.
    """
    if not messages:
        return []
    out: list[dict] = []
    for entry in reversed(messages):
        role = entry.get("role") or ""
        if role == "customer":
            out.append(entry)
            continue
        break  # hit bot or seller_manual — stop walking back
    return list(reversed(out))


# ---------------------------------------------------------------------------
# Redis helpers (sync wrappers — used from the async webhook handler)
# ---------------------------------------------------------------------------

def _redis():
    import redis as _redis_lib
    from app.config import settings
    return _redis_lib.from_url(settings.REDIS_URL, decode_responses=True)


def enqueue_event(page_id: str, customer_ig_id: str, event: dict) -> None:
    """Push one serialised event onto the Redis list for this conversation."""
    key = f"{_BATCH_KEY_PREFIX}{page_id}:{customer_ig_id}"
    r = _redis()
    r.rpush(key, json.dumps(event))
    r.expire(key, 120)  # safety TTL — cleared by the task anyway


def get_pending_task_id(page_id: str, customer_ig_id: str) -> str | None:
    r = _redis()
    return r.get(f"{_TASK_KEY_PREFIX}{page_id}:{customer_ig_id}")


def set_pending_task_id(page_id: str, customer_ig_id: str, task_id: str) -> None:
    r = _redis()
    r.set(f"{_TASK_KEY_PREFIX}{page_id}:{customer_ig_id}", task_id, ex=120)


def pop_all_events(page_id: str, customer_ig_id: str) -> list[dict]:
    key = f"{_BATCH_KEY_PREFIX}{page_id}:{customer_ig_id}"
    r = _redis()
    pipe = r.pipeline()
    pipe.lrange(key, 0, -1)
    pipe.delete(key)
    results = pipe.execute()
    raw_list = results[0] or []
    return [json.loads(item) for item in raw_list]


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(name="app.workers.message_batch.process_message_batch")
def process_message_batch(page_id: str, customer_ig_id: str) -> None:
    run_async(_process_batch(page_id, customer_ig_id))


async def _process_batch(page_id: str, customer_ig_id: str) -> None:
    from app.models.seller import Seller
    from app.models.conversation import Conversation
    from sqlalchemy import select

    events = pop_all_events(page_id, customer_ig_id)
    if not events:
        logger.info("message_batch: no events for %s:%s — skipping", page_id, customer_ig_id)
        return

    logger.info("message_batch: processing %d events for %s:%s", len(events), page_id, customer_ig_id)

    from app.database import worker_session

    async with worker_session() as db:
        # Load seller
        result = await db.execute(
            select(Seller).where(Seller.instagram_page_id == page_id, Seller.is_active == True)
        )
        seller = result.scalar_one_or_none()
        if not seller:
            logger.warning("message_batch: no seller for page_id %s", page_id)
            return

        # Get or create conversation
        from app.api.webhooks.instagram import _get_or_create_conversation
        conversation = await _get_or_create_conversation(seller, customer_ig_id, db)
        await db.flush()

        # Fetch customer name once — only on new conversations where name is not yet known
        if not conversation.customer_name:
            try:
                from app.integrations.instagram import InstagramClient
                ig_client = InstagramClient(seller.instagram_token, seller.fb_page_id)
                user_info = await ig_client.get_user_info(customer_ig_id)
                name = user_info.get("name", "").strip()
                if name:
                    conversation.customer_name = name
                    await db.flush()
                    logger.info("Fetched customer name %r for conversation %s", name, conversation.id)
            except Exception as exc:
                logger.warning("Could not fetch customer name for %s: %s", customer_ig_id, exc)

        if conversation.status == "closed":
            logger.info("message_batch: conversation %s is closed — skipping", conversation.id)
            return

        # Customer disengagement: if the bot already acked a "bye"/"ok" and
        # the quiet window hasn't elapsed, stay silent. A re-engagement signal
        # (buying-intent keyword, 2+ digit token, or question mark) clears the
        # pause immediately so we don't miss a hot lead.
        from app.config import settings as _settings
        if is_bot_paused_for_disengage(conversation.disengage_paused_until):
            text_events = [e for e in events if e.get("type") == "text"]
            if any(is_reengagement_signal(e.get("text")) for e in text_events):
                logger.info(
                    "message_batch: conversation %s disengage pause cleared by re-engagement signal",
                    conversation.id,
                )
                conversation.disengage_paused_until = None
                await db.commit()
                # fall through to normal processing
            else:
                new_entries = extract_customer_text_entries(events)
                if new_entries:
                    msgs = list(conversation.messages or [])
                    msgs.extend(new_entries)
                    conversation.messages = msgs
                    await db.commit()
                logger.info(
                    "message_batch: conversation %s disengage-muted (resume at %s) — recorded %d msg(s)",
                    conversation.id, conversation.disengage_paused_until.isoformat(),
                    len(new_entries),
                )
                return

        # Manual seller takeover: if the seller recently replied from the IG
        # inbox, stay silent until the auto-resume window elapses. We still
        # record customer text messages to conversation history so the bot has
        # the full context when it resumes — only reply generation is skipped.
        if is_bot_paused_for_manual_takeover(
            conversation.last_seller_manual_reply_at,
            _settings.BOT_AUTO_RESUME_AFTER_MINUTES,
        ):
            elapsed = datetime.now(timezone.utc) - conversation.last_seller_manual_reply_at
            new_entries = extract_customer_text_entries(events)
            if new_entries:
                msgs = list(conversation.messages or [])
                msgs.extend(new_entries)
                conversation.messages = msgs
                await db.commit()
            logger.info(
                "message_batch: conversation %s paused (seller manual reply %.1fm ago, window %dm) — recorded %d customer msg(s) without replying",
                conversation.id, elapsed.total_seconds() / 60,
                _settings.BOT_AUTO_RESUME_AFTER_MINUTES,
                len(new_entries),
            )
            return

        # Check active conv_product state
        if conversation.product_id:
            from app.models.conversation_product import ConversationProduct
            cp_result = await db.execute(
                select(ConversationProduct).where(
                    ConversationProduct.conversation_id == conversation.id,
                    ConversationProduct.product_id == conversation.product_id,
                )
            )
            active_cp = cp_result.scalar_one_or_none()
            if active_cp and active_cp.state == "waiting_for_tag":
                logger.info(
                    "message_batch: conversation %s waiting for seller tag — skipping",
                    conversation.id,
                )
                return

        await _process_events(events, conversation, seller, db)


async def _process_events(events: list, conversation, seller, db) -> None:
    """
    Combine all events in the batch into a single bot reply:

    1. Payment screenshot → processed immediately and returned (urgent).
    2. Images / reels   → run product identification (no reply sent), which
                          sets conversation.product_id and state as context.
    3. Text messages    → concatenated into one string.
    4. One call to advance_conversation with the combined text (or a synthetic
       message if no text was present) generates and sends the single reply.
    """
    from app.bot.conversation import advance_conversation, handle_product_image, handle_payment_screenshot, handle_reel
    from app.api.webhooks.instagram import _IG_URL_RE

    # Phase 1 — media events: identify products / match reels (context only, no reply).
    # For images in awaiting_payment state, classify first — customer might be sending
    # a product image (new inquiry) rather than a payment screenshot.
    import base64 as _b64
    import httpx as _httpx
    from app.bot.conversation import _classify_image_type, _detect_media_type

    # Determine the active conv_product state for routing decisions
    _active_cp_state = None
    if conversation.product_id:
        from app.models.conversation_product import ConversationProduct as _CP
        _cp_res = await db.execute(
            select(_CP).where(
                _CP.conversation_id == conversation.id,
                _CP.product_id == conversation.product_id,
            )
        )
        _cp = _cp_res.scalar_one_or_none()
        if _cp:
            _active_cp_state = _cp.state

    for event in events:
        etype = event.get("type")
        if etype == "image":
            image_url = event["image_url"]

            if _active_cp_state == "awaiting_payment":
                # Download once, classify, then route
                try:
                    async with _httpx.AsyncClient(timeout=15) as http:
                        img_resp = await http.get(image_url)
                        img_resp.raise_for_status()
                    img_b64 = _b64.b64encode(img_resp.content).decode()
                    media_type = _detect_media_type(img_resp.content)
                    image_class = await _classify_image_type(img_b64, media_type)
                    logger.info("Image classified as %r in awaiting_payment state", image_class)
                except Exception as exc:
                    logger.warning("Image classification failed: %s — treating as payment", exc)
                    image_class = "payment"

                if image_class == "payment":
                    await handle_payment_screenshot(conversation, seller, image_url, db)
                    return  # payment confirmed — stop processing the batch
                else:
                    # Product image — customer is asking about a new product
                    await handle_product_image(conversation, seller, image_url, db, send_reply=False)
            else:
                await handle_product_image(conversation, seller, image_url, db, send_reply=False)

        elif etype == "reel":
            # Check for Instagram URL in text too
            ig_url = event.get("reel_url", "")
            await handle_reel(
                conversation, seller, ig_url, db,
                reel_video_id=event.get("reel_video_id"),
                reel_title=event.get("reel_title"),
                send_reply=False,
            )

    # Phase 2 — collect all text parts (including IG URLs in text messages).
    # If the customer replied to a specific old message, resolve that context first.
    from app.bot.conversation import find_message_by_mid
    text_parts = []
    reply_context_prefix = ""
    customer_mid: str | None = None

    for event in events:
        if event.get("type") == "text":
            text = event["text"]
            customer_mid = event.get("mid") or customer_mid  # keep last non-null mid

            # Resolve reply_to context from the first event that carries one
            if not reply_context_prefix and event.get("reply_to_mid"):
                ref = find_message_by_mid(conversation, event["reply_to_mid"])
                if ref:
                    role_label = "Bot" if ref["role"] == "bot" else "Customer"
                    ref_product_id = ref.get("product_id")
                    current_product_id = str(conversation.product_id) if conversation.product_id else None

                    if ref_product_id and current_product_id and ref_product_id != current_product_id:
                        # Customer is replying to a message about a different product —
                        # switch the conversation to that product so the answer is correct.
                        from app.models.product import Product as _Product
                        from sqlalchemy import select as _select
                        r1 = await db.execute(_select(_Product).where(_Product.id == ref_product_id))
                        ref_product = r1.scalar_one_or_none()
                        if ref_product:
                            conversation.product_id = ref_product_id
                            logger.info(
                                "reply_to switched product: %s → %s",
                                current_product_id, ref_product.name,
                            )
                        ref_name = ref_product.name if ref_product else ref_product_id
                        reply_context_prefix = (
                            f"[Customer is replying to {role_label}'s message about '{ref_name}': \"{ref['content']}\"]\n"
                        )
                    else:
                        reply_context_prefix = (
                            f"[Customer is replying to {role_label}'s message: \"{ref['content']}\"]\n"
                        )
                    logger.info("reply_to context: %r", reply_context_prefix.strip())
                else:
                    logger.info("reply_to mid=%s not found in history", event["reply_to_mid"])

            ig_match = _IG_URL_RE.search(text)
            if ig_match and conversation.status == "active":
                await handle_reel(conversation, seller, ig_match.group(0), db, send_reply=False)
            else:
                text_parts.append(text)

    # Phase 3 — one advance_conversation call with everything combined
    has_media = any(e.get("type") in ("image", "reel") for e in events)

    if text_parts:
        combined_text = reply_context_prefix + "\n".join(text_parts)
        logger.info("message_batch: combined text=%r (had_media=%s)", combined_text, has_media)
        await advance_conversation(conversation, seller, combined_text, db, send_reply=True, customer_mid=customer_mid)
    elif has_media:
        combined_text = reply_context_prefix + "[customer sent media]"
        await advance_conversation(conversation, seller, combined_text, db, send_reply=True)
    # else: nothing actionable, no reply


# ---------------------------------------------------------------------------
# Proactive wake-up: when the seller takeover pause window expires AND the
# customer is still waiting, this task fires and generates the bot reply that
# the reactive gate (which only fires on inbound webhooks) would have missed.
# Scheduled by _handle_echo_event in webhooks/instagram.py.
# ---------------------------------------------------------------------------

@celery_app.task(name="app.workers.message_batch.wake_paused_conversation")
def wake_paused_conversation(conversation_id: str) -> None:
    run_async(_wake_paused_conversation(conversation_id))


@celery_app.task(name="app.workers.message_batch.scan_resume_paused_conversations")
def scan_resume_paused_conversations() -> None:
    run_async(_scan_resume_paused_conversations())


async def _scan_resume_paused_conversations() -> None:
    """Beat-driven scan that finds conversations whose seller-takeover pause
    window has expired and dispatches wake_paused_conversation for each.

    Replaces the fragile per-message ETA scheduling: celery countdown tasks
    sit in worker memory and don't survive restarts, so a deploy during the
    6h default window silently drops the wake-up. A periodic scan is
    idempotent and survives any restart.
    """
    from app.models.conversation import Conversation
    from app.database import worker_session
    from app.config import settings as _settings

    threshold = datetime.now(timezone.utc) - timedelta(
        minutes=_settings.BOT_AUTO_RESUME_AFTER_MINUTES
    )
    async with worker_session() as db:
        result = await db.execute(
            select(Conversation.id).where(
                Conversation.status == "active",
                Conversation.last_seller_manual_reply_at.isnot(None),
                Conversation.last_seller_manual_reply_at < threshold,
            )
        )
        ids = [str(cid) for (cid,) in result.all()]

    if not ids:
        return

    logger.info("scan_resume_paused_conversations: dispatching wake for %d conversation(s)", len(ids))
    for cid in ids:
        wake_paused_conversation.apply_async(args=[cid])


async def _wake_paused_conversation(conversation_id: str) -> None:
    from app.models.conversation import Conversation
    from app.models.seller import Seller
    from app.database import worker_session
    from app.config import settings as _settings
    from app.bot.conversation import advance_conversation

    async with worker_session() as db:
        result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
        conversation = result.scalar_one_or_none()
        if not conversation:
            logger.info("wake_paused_conversation: conversation %s not found — skip", conversation_id)
            return

        if conversation.status == "closed":
            logger.info("wake_paused_conversation: conversation %s closed — skip", conversation_id)
            return

        if is_bot_paused_for_manual_takeover(
            conversation.last_seller_manual_reply_at,
            _settings.BOT_AUTO_RESUME_AFTER_MINUTES,
        ):
            logger.info(
                "wake_paused_conversation: conversation %s still paused (newer seller reply pushed timestamp) — skip",
                conversation_id,
            )
            return

        pending = unanswered_customer_messages(conversation.messages)
        if not pending:
            logger.info(
                "wake_paused_conversation: conversation %s already answered — skip",
                conversation_id,
            )
            return

        seller_result = await db.execute(select(Seller).where(Seller.id == conversation.seller_id))
        seller = seller_result.scalar_one_or_none()
        if not seller or not seller.is_active:
            logger.info("wake_paused_conversation: seller %s inactive — skip", conversation.seller_id)
            return

        combined_text = "\n".join((e.get("content") or "").strip() for e in pending if (e.get("content") or "").strip())
        last_mid = pending[-1].get("mid")
        logger.info(
            "wake_paused_conversation: conversation %s — replying to %d customer msg(s)",
            conversation_id, len(pending),
        )
        await advance_conversation(
            conversation, seller, combined_text, db,
            send_reply=True, resume=True, customer_mid=last_mid,
        )
