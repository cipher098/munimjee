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
import json
import logging
import signal

import boto3

from app.config import settings
from app.database import worker_session
from app.api.webhooks.instagram import _handle_messaging_event

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sqs_consumer")

_stop = False


def _request_stop(*_):
    global _stop
    _stop = True
    logger.info("Shutdown signal received — finishing current poll then exiting")


async def _process_event(messaging_event: dict) -> None:
    async with worker_session() as db:
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
