"""
Celery task: process a batch of messages from the same customer that arrived within
a 15-second debounce window.  Each incoming webhook event is queued in Redis;
a delayed task fires after 15 s of silence and processes them all, sending exactly
one bot reply.
"""
import asyncio
import json
import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

BATCH_WINDOW_SECONDS = 15
_BATCH_KEY_PREFIX = "msg_batch:"
_TASK_KEY_PREFIX = "msg_batch_task:"


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
    asyncio.run(_process_batch(page_id, customer_ig_id))


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

        TERMINAL = {"payment_confirmed", "failed", "dispatched_notified"}
        if conversation.state in TERMINAL:
            logger.info("message_batch: conversation %s is terminal — skipping", conversation.id)
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

    # Payment screenshots must be handled immediately — don't batch them
    for event in events:
        if event.get("type") == "image" and conversation.state == "awaiting_payment":
            await handle_payment_screenshot(conversation, seller, event["image_url"], db)
            return

    # Phase 1 — media events: identify products / match reels (context only, no reply)
    for event in events:
        etype = event.get("type")
        if etype == "image":
            await handle_product_image(conversation, seller, event["image_url"], db, send_reply=False)
        elif etype == "reel":
            # Check for Instagram URL in text too
            ig_url = event.get("reel_url", "")
            await handle_reel(
                conversation, seller, ig_url, db,
                reel_video_id=event.get("reel_video_id"),
                reel_title=event.get("reel_title"),
                send_reply=False,
            )

    # Phase 2 — collect all text parts (including IG URLs in text messages)
    text_parts = []
    for event in events:
        if event.get("type") == "text":
            text = event["text"]
            ig_match = _IG_URL_RE.search(text)
            if ig_match and conversation.state not in ("payment_confirmed", "dispatched_notified", "failed"):
                # Treat inline reel URL as a reel event for context
                await handle_reel(conversation, seller, ig_match.group(0), db, send_reply=False)
            else:
                text_parts.append(text)

    # Phase 3 — one advance_conversation call with everything combined
    has_media = any(e.get("type") in ("image", "reel") for e in events)

    if text_parts:
        combined_text = "\n".join(text_parts)
        logger.info("message_batch: combined text=%r (had_media=%s)", combined_text, has_media)
        await advance_conversation(conversation, seller, combined_text, db, send_reply=True)
    elif has_media:
        # Media only — product context is set; let advance_conversation generate the natural reply
        await advance_conversation(conversation, seller, "[customer sent media]", db, send_reply=True)
    # else: nothing actionable, no reply
