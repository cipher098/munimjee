"""Shared Instagram conversation policy and legacy Redis cutover transfer.

New webhook messages live in the durable inbox. Old Redis batch tasks transfer
buffered events into that same inbox and fence them for review before sending.
The durable worker owns dispatch; takeover resume and nudges share its thread
lock/quarantine gate.
"""
from app.workers.async_runner import run_async
from datetime import datetime, timedelta, timezone
import json
import logging
import re

from sqlalchemy import select
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

BATCH_WINDOW_SECONDS = 20
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


# A disengage pause is only meant to stop the bot pestering after a genuine drop-off
# ("ok", "let me think", "bye"). The customer coming BACK with anything substantive — a buy
# signal ("bhaiya kardo pack"), a price objection ("ye mehangi hai"), a question, a new
# product — must wake the bot. Bias: a false positive costs one extra ack, a false negative
# LOSES A SALE. So we wake on EVERYTHING except a short, pure acknowledgement/goodbye.
_DISENGAGE_ONLY_PHRASES = {
    "ok", "okay", "okk", "k", "kk", "kkk", "okie", "ok ji", "okay ji",
    "hmm", "hm", "hmmm", "acha", "achha", "accha", "acha ji", "hmm ok", "ok hmm",
    "thik", "thik hai", "theek", "theek hai", "thik h", "thik hai ji", "theek hai ji",
    "ok thik", "ok thik hai", "thik hai bye",
    "thanks", "thank you", "thank u", "thanx", "thnx", "ty", "tysm", "shukriya",
    "ok thanks", "ok thank you", "thanks ji",
    "bye", "ok bye", "byee", "ttyl", "gn", "good night", "gm", "good morning",
    "baad mein", "baad me", "later", "abhi nahi", "abhi nhi", "abhi nahin",
    "let me think", "sochta hoon", "sochti hoon", "soch ke", "sochke batata hoon",
    "sochke batati hoon", "sochke batata hu", "sochke batati hu", "dekhta hoon",
    "dekhti hoon", "dekhte hain", "dekhenge", "phir batata hoon", "phir batati hoon",
    "kal dekhte hai", "kal dekhte hain", "kal batata hoon", "kal batati hoon",
}

# Clear refusals (substring match) — the customer is declining, not returning. Stay muted so
# the bot doesn't re-ack a "no". (Buy/negotiation/questions are NOT here — they wake.)
_REFUSAL_MARKERS = (
    "nahi chahiye", "nhi chahiye", "nahi chaiye", "nhi chaiye",
    "nahi lena", "nhi lena", "nahin lena", "nahi lunga", "nahin lunga", "nhi lunga",
    "rehne do", "rhne do", "rehndo", "chhod do", "chod do",
    "mat bhej", "not interested", "no thanks", "interested nahi", "nahi karna",
)


def is_reengagement_signal(text: str | None) -> bool:
    """True when the disengage pause should drop — i.e. the customer came back with anything
    real (buy signal, price objection, question, new product…). We mute ONLY a short pure
    acknowledgement/goodbye or a clear refusal; everything else wakes the bot (biased to
    never miss a returning buyer — a false positive is one extra ack, a false negative loses
    the sale)."""
    if not text:
        return False
    if "?" in text:
        return True  # the customer is actively asking — wake
    # Normalize: lowercase, strip punctuation/emoji, collapse whitespace.
    norm = re.sub(r"[^\w\s]", " ", text.lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    if not norm:
        return False  # emoji/punctuation-only — passive ack, stay muted
    if norm in _DISENGAGE_ONLY_PHRASES:
        return False  # pure ack/goodbye — stay muted
    if any(m in norm for m in _REFUSAL_MARKERS):
        return False  # explicit refusal — stay muted
    return True  # anything substantive → wake


# Post-payment change requests the bot must NOT auto-handle — they go to the seller.
# (substring match on normalized text; gated on "money already received" by the caller)
_POST_ORDER_CHANGE = (
    ("refund", "refund"), ("paisa wapas", "refund"), ("paise wapas", "refund"),
    ("paise return", "refund"), ("money back", "refund"), ("paise vapas", "refund"),
    ("cancel", "cancellation"), ("order cancel", "cancellation"), ("rad kar", "cancellation"),
    ("radd kar", "cancellation"), ("cancel kar", "cancellation"),
    ("exchange", "item_change"), ("badal do", "item_change"), ("badal dena", "item_change"),
    ("badal kar", "item_change"), ("ki jagah", "item_change"), ("replace", "item_change"),
    ("wapas le lo", "item_change"), ("return kar", "item_change"), ("change kar do", "item_change"),
    ("doosra bhej", "item_change"), ("dusra bhej", "item_change"),
)


def post_order_change_kind(text: str | None) -> str | None:
    """If the customer's text is a refund/cancellation/item-change request, return its kind
    ('refund' | 'cancellation' | 'item_change'); else None. Caller gates this on whether a
    payment has actually been received (so pre-payment cancels/changes stay automated)."""
    if not text:
        return None
    norm = re.sub(r"[^\w\s]", " ", text.lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    for phrase, kind in _POST_ORDER_CHANGE:
        if phrase in norm:
            return kind
    return None


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

async def _lock_conversation(db, conversation_id) -> None:
    """Serialize all bot REPLY work for one conversation across the two paths
    that can each send a reply — the message-batch path and the seller-takeover
    resume scan (_wake_paused_conversation).

    Without this they race: the resume scan reads conversation.messages and sees
    the customer's message as "unanswered" before a concurrently-running batch
    has committed its bot reply, so both reply → the customer gets two messages.

    A pg advisory *xact* lock is held until the surrounding transaction commits,
    so whoever runs second blocks here, then re-reads state (now including the
    first reply) and skips. Keyed on the conversation id.
    """
    from sqlalchemy import text
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:cid))"),
        {"cid": str(conversation_id)},
    )


def _redis():
    import redis as _redis_lib
    from app.config import settings
    return _redis_lib.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)


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


def peek_all_events(page_id: str, customer_ig_id: str) -> list[dict]:
    """Read legacy queued events without removing them. Redis retains them
    until trim_processed_events() after commit, subject to the legacy TTL.
    New webhook messages use the durable Instagram inbox instead."""
    key = f"{_BATCH_KEY_PREFIX}{page_id}:{customer_ig_id}"
    r = _redis()
    raw_list = r.lrange(key, 0, -1) or []
    return [json.loads(item) for item in raw_list]


def _snapshot_legacy_events(page_id: str, customer_ig_id: str) -> tuple[list[dict], list[str]]:
    """Persist per-item transfer IDs before importing missing-mid Redis work.

    IDs survive retries; a subsequent identical buffer receives fresh IDs. Return
    exact serialized bytes for compare-and-trim after the database commit.
    """
    from uuid import uuid4
    key = f"{_BATCH_KEY_PREFIX}{page_id}:{customer_ig_id}"
    script = """
    redis.call('PERSIST', KEYS[1])
    local items = redis.call('LRANGE', KEYS[1], 0, -1)
    for i, raw in ipairs(items) do
        local item = cjson.decode(raw)
        if not item.mid or item.mid == cjson.null or item.mid == '' then
            if not item._legacy_transfer_id or item._legacy_transfer_id == cjson.null then
                item._legacy_transfer_id = ARGV[1] .. ':' .. i
                items[i] = cjson.encode(item)
                redis.call('LSET', KEYS[1], i - 1, items[i])
            end
        end
    end
    return items
    """
    raw = _redis().eval(script, 1, key, uuid4().hex) or []
    return [json.loads(item) for item in raw], raw


def trim_processed_events(page_id: str, customer_ig_id: str, count: int, *, expected_events=None, expected_raw=None) -> None:
    """Trim only the exact transferred prefix after DB commit.

    A concurrent legacy task may already have trimmed it. Comparing the prefix
    prevents the stale task from deleting newly arrived events in its place.
    """
    if count <= 0:
        return
    key = f"{_BATCH_KEY_PREFIX}{page_id}:{customer_ig_id}"
    if expected_raw is None:
        if expected_events is None:
            raise ValueError("Expected Redis prefix required")
        expected_raw = [json.dumps(event) for event in expected_events]
    script = """
    for i = 1, #ARGV do
        if redis.call('LINDEX', KEYS[1], i - 1) ~= ARGV[i] then return 0 end
    end
    redis.call('LTRIM', KEYS[1], #ARGV, -1)
    return #ARGV
    """
    _redis().eval(script, 1, key, *expected_raw)


def drop_all_events(page_id: str, customer_ig_id: str) -> None:
    """Dead-letter: discard the whole queue (used when a batch can't ever succeed)."""
    _redis().delete(f"{_BATCH_KEY_PREFIX}{page_id}:{customer_ig_id}")


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.workers.message_batch.process_message_batch",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=None,
)
def process_message_batch(self, page_id: str, customer_ig_id: str) -> None:
    try:
        run_async(_process_batch(page_id, customer_ig_id))
    except Exception as exc:
        # This task only transfers old Redis work into the durable inbox.
        # Never drop accepted work when the DB is unavailable. The Redis key is
        # retained without expiry by _process_batch before attempting transfer.
        raise self.retry(exc=exc, countdown=min(2 ** min(self.request.retries, 5), 30), max_retries=None)


def _record_customer_entries(conversation, events) -> None:
    """Append the batch's customer text turns to history, deduped by mid so a
    retry/redelivery doesn't duplicate them (idempotent)."""
    existing = {m.get("mid") for m in (conversation.messages or []) if m.get("mid")}
    new_entries = [
        e for e in extract_customer_text_entries(events)
        if not e.get("mid") or e["mid"] not in existing
    ]
    if new_entries:
        conversation.messages = list(conversation.messages or []) + new_entries


async def _process_batch(page_id: str, customer_ig_id: str) -> None:
    # Read WITHOUT removing — legacy events stay in Redis until we
    # successfully commit, so a crash/retry reprocesses them instead of losing them.
    events, raw = _snapshot_legacy_events(page_id, customer_ig_id)
    if not events:
        logger.info("message_batch: no events for %s:%s — skipping", page_id, customer_ig_id)
        return

    logger.info("message_batch: processing %d events for %s:%s", len(events), page_id, customer_ig_id)

    consumed = await _consume_batch(page_id, customer_ig_id, events=events)
    # Reached only if _consume_batch returned normally → its transaction committed.
    # Trim the events we consumed; anything that arrived meanwhile survives.
    trim_processed_events(page_id, customer_ig_id, consumed, expected_raw=raw[:consumed])


async def _consume_batch(page_id: str, customer_ig_id: str, *, events=None) -> int:
    """Durably transfer legacy Redis work; this path never sends replies.

    Every transferred receipt is fenced for cutover review unless its provider
    mid is already completed in the shared ledger. Redis is trimmed after commit.
    """
    from app.models.seller import Seller
    from app.database import worker_session
    from app.services.instagram_ingress import persist_legacy_batch

    events = peek_all_events(page_id, customer_ig_id) if events is None else events
    if not events:
        return 0
    async with worker_session() as db:
        sellers = (await db.execute(select(Seller).where(
            Seller.instagram_page_id == page_id, Seller.is_active.is_(True),
        ).limit(2))).scalars().all()
        if len(sellers) != 1:
            raise ValueError("Legacy Instagram account requires cutover review")
        return await persist_legacy_batch(db, sellers[0], page_id, customer_ig_id, events)


async def _consume_events(db, seller, customer_ig_id: str, events: list[dict], *, owned_receipt_ids=()) -> set[int]:
    """Single conversation writer; return exactly which event indices were consumed.

    The caller owns the transaction and receipt completion. The same advisory
    lock and quarantine gate also serialize/block takeover resume and nudges.
    """
    from app.config import settings as _settings
    from app.api.webhooks.instagram import _get_or_create_conversation
    conversation = await _get_or_create_conversation(seller, customer_ig_id, db)
    await db.flush()

    await _lock_conversation(db, conversation.id)
    await db.refresh(conversation)
    from app.services.instagram_ingress import thread_quarantined
    from app.services.channel_readiness import instagram_automation_enabled
    if not await instagram_automation_enabled(db, seller.id):
        return set()
    if await thread_quarantined(db, seller.id, customer_ig_id, owned_receipt_ids=owned_receipt_ids):
        return set()
    if not events:
        return set()
    consumed = set(range(len(events)))

    # Fetch customer name only after the thread passed its quarantine gate.
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

    # Post-payment change requests (refund / cancellation / item-change) are NEVER
    # auto-handled. While an OPEN manual action exists the bot stays silent on this chat
    # until the seller marks it resolved in the dashboard. (A NEW change request is
    # detected by the decide LLM inside advance_conversation — see responder — so typos
    # don't matter; here we only enforce the mute once one is open.)
    from app.models.manual_action import ManualAction as _MA
    _open_ma = (await db.execute(
        select(_MA).where(_MA.conversation_id == conversation.id, _MA.status == "open").limit(1)
    )).scalars().first()
    if _open_ma is not None:
        _record_customer_entries(conversation, events)
        await db.flush()
        logger.info("message_batch: %s muted — open manual action (%s); recorded customer msg(s)",
                    conversation.id, _open_ma.kind)
        return consumed

    # Customer disengagement pause.
    if is_bot_paused_for_disengage(conversation.disengage_paused_until):
        text_events = [e for e in events if e.get("type") == "text"]
        if any(is_reengagement_signal(e.get("text")) for e in text_events):
            logger.info("message_batch: %s disengage pause cleared by re-engagement signal", conversation.id)
            conversation.disengage_paused_until = None
            await db.flush()
            # fall through to normal processing
        else:
            _record_customer_entries(conversation, events)
            await db.flush()
            logger.info("message_batch: %s disengage-muted (resume at %s) — recorded customer msg(s)",
                        conversation.id, conversation.disengage_paused_until.isoformat())
            return consumed

    # Manual seller takeover pause — record customer messages, don't reply.
    if is_bot_paused_for_manual_takeover(
        conversation.last_seller_manual_reply_at, _settings.BOT_AUTO_RESUME_AFTER_MINUTES,
    ):
        _record_customer_entries(conversation, events)
        await db.flush()
        logger.info("message_batch: %s paused (seller manual takeover) — recorded customer msg(s) without replying", conversation.id)
        return consumed

    from app.services import sku_fact_replies as facts
    await facts.freeze_instagram_batch(db, seller.id, conversation, events)

    # waiting_for_tag: the bot paused because it couldn't answer a feature
    # question and pinged the seller. But the customer has sent a NEW message
    # (often about a different product) — don't keep the WHOLE conversation
    # muted waiting on the seller. Release the pause and process; if they re-ask
    # the same unanswerable feature, the responder re-pauses for that turn only.
    # The open seller alert stays so the seller can still fill the tag.
    if conversation.product_id:
        from app.models.conversation_product import ConversationProduct
        cp_result = await db.execute(
            select(ConversationProduct).where(
                ConversationProduct.conversation_id == conversation.id,
                ConversationProduct.product_id == conversation.product_id,
            ).order_by(ConversationProduct.created_at.desc()).limit(1)
        )
        active_cp = cp_result.scalars().first()
        preserve_sku_cycle = conversation._sku_batch_facts_allowed
        if active_cp and active_cp.state == "waiting_for_tag" and not preserve_sku_cycle:
            logger.info("message_batch: %s releasing waiting_for_tag to process new message", conversation.id)
            active_cp.state = "product_inquiry"
            active_cp.pending_tag_id = None
            await db.flush()

    return await _process_events(events, conversation, seller, db)

async def _process_events(events: list, conversation, seller, db) -> set[int]:
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

    from app.services import sku_fact_replies as facts
    if getattr(conversation, '_sku_batch_events', None) is not events:
        await facts.freeze_instagram_batch(db, seller.id, conversation, events)

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
            ).order_by(_CP.created_at.desc()).limit(1)
        )
        _cp = _cp_res.scalars().first()
        if _cp:
            _active_cp_state = _cp.state

    handled_media = set()
    for index, event in enumerate(events):
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

                # In awaiting_payment, treat ANY image as a payment-proof attempt.
                # The verifier downgrades a non-payment / wrong payment to manual
                # review (or tells the customer it went to the wrong UPI), so a
                # misclassified screenshot is never silently handled as a product
                # image (which used to re-share the QR instead of flagging it).
                if image_class != "payment":
                    logger.info("Image classified %r but state is awaiting_payment — verifying as payment", image_class)
                await handle_payment_screenshot(conversation, seller, image_url, db)
                handled_media.add(index)
                return handled_media
            else:
                await handle_product_image(conversation, seller, image_url, db, send_reply=False)
                handled_media.add(index)

        elif etype == "reel":
            # Check for Instagram URL in text too
            ig_url = event.get("reel_url", "")
            await handle_reel(
                conversation, seller, ig_url, db,
                reel_video_id=event.get("reel_video_id"),
                reel_title=event.get("reel_title"),
                send_reply=False,
            )
            handled_media.add(index)

    # Phase 2 — collect all text parts (including IG URLs in text messages).
    # If the customer replied to a specific old message, resolve that context first.
    from app.bot.conversation import find_message_by_mid
    text_parts = []
    reply_context_prefix = ""
    customer_mid: str | None = None
    sku_reel_context = False

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

                    if ref_product_id and ref_product_id != current_product_id:
                        # Customer is replying to a message about a specific product
                        # (and it isn't already the focus — including when there is
                        # no focus yet, e.g. after a multi-photo send) — switch the
                        # conversation to that product so the answer is correct.
                        from app.models.product import Product as _Product
                        from sqlalchemy import select as _select
                        r1 = await db.execute(_select(_Product).where(_Product.id == ref_product_id,
                            _Product.seller_id == seller.id, _Product.active.is_(True)))
                        ref_product = r1.scalar_one_or_none()
                        if ref_product:
                            from app.services.channel_readiness import guard_legacy_product
                            from app.services import sku_fact_replies as facts
                            if not facts.enabled() or not await facts.is_activated(db, seller.id, ref_product.id):
                                await guard_legacy_product(db, seller.id, ref_product.id)
                            conversation.product_id = ref_product_id
                            logger.info(
                                "reply_to switched product: %s → %s",
                                current_product_id, ref_product.name,
                            )
                        else:
                            from app.services import sku_fact_replies as facts
                            if facts.enabled():
                                from app.services.channel_readiness import CatalogueAuthorityHandoff
                                raise CatalogueAuthorityHandoff("Explicit reply product is unavailable")
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
            if ig_match:
                await handle_reel(conversation, seller, ig_match.group(0), db, send_reply=False)
                from app.services import sku_fact_replies as facts
                if facts.enabled() and await facts.is_activated(db, seller.id, conversation.product_id):
                    sku_reel_context = True
                    question = text[:ig_match.start()] + text[ig_match.end():]
                    if question.strip():
                        text_parts.append(question.strip())
            else:
                text_parts.append(text)

    # Phase 3 — one advance_conversation call with everything combined
    has_media = sku_reel_context or any(e.get("type") in ("image", "reel") for e in events)

    if text_parts:
        from app.services import sku_fact_replies as facts
        if facts.enabled() and await facts.is_activated(db, seller.id, conversation.product_id):
            # Historical quoted text may contain obsolete prices. It supplies
            # only the explicit product reference, never read-fact authority.
            reply_context_prefix = ""
        combined_text = reply_context_prefix + "\n".join(text_parts)
        logger.info("message_batch: combined text=%r (had_media=%s)", combined_text, has_media)
        await advance_conversation(conversation, seller, combined_text, db, send_reply=True, customer_mid=customer_mid)
    elif has_media:
        combined_text = reply_context_prefix + "[customer sent media]"
        await advance_conversation(conversation, seller, combined_text, db, send_reply=True)
    # else: nothing actionable, no reply
    return set(range(len(events)))


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

    now = datetime.now(timezone.utc)
    threshold = now - timedelta(minutes=_settings.BOT_AUTO_RESUME_AFTER_MINUTES)
    async with worker_session() as db:
        result = await db.execute(
            select(Conversation.id).where(
                Conversation.last_seller_manual_reply_at.isnot(None),
                Conversation.last_seller_manual_reply_at < threshold,
                # Skip conversations still in a disengage pause — waking them
                # would trigger Claude and immediately re-ack on a "bye" loop.
                (Conversation.disengage_paused_until.is_(None))
                | (Conversation.disengage_paused_until < now),
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
        # Take the per-conversation lock BEFORE reading state, so if a message
        # batch is mid-reply we block until it commits and then see its reply
        # (the pending re-check below will skip). Prevents double replies.
        await _lock_conversation(db, conversation_id)
        result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
        conversation = result.scalar_one_or_none()
        if not conversation:
            logger.info("wake_paused_conversation: conversation %s not found — skip", conversation_id)
            return

        from app.services.channel_readiness import instagram_automation_enabled, guard_legacy_product, CatalogueAuthorityHandoff
        if not await instagram_automation_enabled(db, conversation.seller_id):
            return
        try:
            await guard_legacy_product(db, conversation.seller_id, conversation.product_id)
        except CatalogueAuthorityHandoff:
            return
        from app.services.instagram_ingress import thread_quarantined
        if await thread_quarantined(db, conversation.seller_id, conversation.customer_instagram_id):
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

        # Also honour the disengage pause — without this the seller-takeover
        # scan would wake the bot during a customer-disengagement quiet window
        # and immediately fire another acknowledge_and_close, looping every
        # scan tick.
        if is_bot_paused_for_disengage(conversation.disengage_paused_until):
            logger.info(
                "wake_paused_conversation: conversation %s disengage-paused until %s — skip",
                conversation_id, conversation.disengage_paused_until.isoformat(),
            )
            return

        pending = unanswered_customer_messages(conversation.messages)
        from app.services.channel_readiness import resume_messages_after_review
        pending = await resume_messages_after_review(db, conversation.seller_id, conversation.customer_instagram_id, pending)
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
