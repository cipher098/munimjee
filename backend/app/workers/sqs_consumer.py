"""SQS consumer — drains the webhook ingress queue into the bot pipeline.

The ingress Lambda (infra/lambda/handler.py) validates + enqueues one SQS FIFO
message per Instagram messaging event. This process long-polls that queue and
replays each event through the SAME logic the old FastAPI webhook used —
``_handle_messaging_event`` — which does seller lookup, echo classification,
and the Redis-batch + Celery scheduling.

Run it as its own container alongside api/worker/beat (see
docker-compose.prod.yml). If this process or the whole VPS is down, events stay
safely in SQS (up to 14 days) and are processed when it comes back.

FIFO note: messages are processed sequentially and deleted only on success.
Per ``MessageGroupId`` (one conversation), SQS won't release the next message
until the current one is deleted, so conversation order is preserved. A message
that raises is left undeleted → redelivered → after maxReceiveCount lands in the
DLQ, never blocking the rest of the queue.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import signal

import boto3
import httpx

from app.config import settings
from app.database import worker_session
from app.api.webhooks.instagram import _handle_messaging_event, _get_seller_by_page_id

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sqs_consumer")

_stop = False


def _request_stop(*_):
    global _stop
    _stop = True
    logger.info("Shutdown signal received — finishing current poll then exiting")


def _page_id_for(event: dict) -> str:
    """The seller's IG page id for this event.

    For an inbound customer message the page is the recipient; for an echo (the
    seller's own send) the page is the sender. Used to decide local routing.
    """
    if (event.get("message") or {}).get("is_echo"):
        return event.get("sender", {}).get("id", "")
    return event.get("recipient", {}).get("id", "")


async def _maybe_route_to_local(event: dict, db) -> bool:
    """Live-debug hook: if this event belongs to a seller flagged in
    ROUTE_TO_LOCAL_SELLER_IDS, forward it to a developer's local environment
    (LOCAL_WEBHOOK_URL) and return True so prod skips normal processing. All
    other sellers are unaffected. Off when the list is empty.
    """
    if not settings.ROUTE_TO_LOCAL_SELLER_IDS:
        return False
    page_id = _page_id_for(event)
    if not page_id:
        return False
    seller = await _get_seller_by_page_id(page_id, db)
    if not seller or str(seller.id) not in settings.ROUTE_TO_LOCAL_SELLER_IDS:
        return False
    await _forward_to_local(event)
    logger.info("Routed event for seller %s (page %s) → %s",
                seller.id, page_id, settings.LOCAL_WEBHOOK_URL)
    return True


async def _forward_to_local(event: dict) -> None:
    """POST the event to LOCAL_WEBHOOK_URL in Meta's webhook shape, signed with
    META_WEBHOOK_SECRET so the dev app's signature check passes (same Meta app).
    Raises on failure so the SQS message is retried (then DLQ'd) — e.g. if the
    local tunnel is down.
    """
    payload = {"object": "instagram", "entry": [{"messaging": [event]}]}
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if settings.META_WEBHOOK_SECRET:
        sig = hmac.new(settings.META_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Hub-Signature-256"] = "sha256=" + sig
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(settings.LOCAL_WEBHOOK_URL, content=body, headers=headers)
        resp.raise_for_status()


async def _process_event(messaging_event: dict) -> None:
    async with worker_session() as db:
        if await _maybe_route_to_local(messaging_event, db):
            return
        await _handle_messaging_event(messaging_event, db)


def _handle_message(msg: dict) -> None:
    messaging_event = json.loads(msg["Body"])
    asyncio.run(_process_event(messaging_event))


def run() -> None:
    if not settings.SQS_QUEUE_URL:
        raise RuntimeError("SQS_QUEUE_URL is not set")

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    sqs = boto3.client("sqs", region_name=settings.AWS_REGION)
    queue_url = settings.SQS_QUEUE_URL
    logger.info("Polling %s", queue_url)

    while not _stop:
        resp = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20,       # long-poll
            VisibilityTimeout=60,
        )
        for msg in resp.get("Messages", []):
            try:
                _handle_message(msg)
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])
            except Exception:
                # Leave it on the queue — SQS will redeliver, then DLQ it after
                # maxReceiveCount. Do NOT delete a message we failed to process.
                logger.exception("Failed to process message %s; leaving for retry", msg.get("MessageId"))

    logger.info("Consumer stopped")


if __name__ == "__main__":
    run()
