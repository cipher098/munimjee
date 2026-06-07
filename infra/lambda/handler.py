"""Instagram webhook ingress Lambda.

Sits behind API Gateway (HTTP API, payload format 2.0) on hooks.munimjee.in.
Its only job is to ACCEPT Meta's webhook reliably and durably — it does NOT
run any bot logic. That keeps the accept path independent of the app VPS:

  Meta ──▶ API Gateway ──▶ this Lambda ──▶ SQS FIFO ──▶ sqs_consumer (on the VPS)

Behaviour mirrors the original FastAPI handler
(app/api/webhooks/instagram.py):

  * GET  — echo hub.challenge when hub.verify_token matches META_VERIFY_TOKEN.
  * POST — validate X-Hub-Signature-256 over the RAW body, then push one SQS
           message per messaging event and return 200 fast.

Runtime deps: stdlib + boto3 (boto3 is preinstalled in the Lambda runtime).

Env vars:
  META_VERIFY_TOKEN    — challenge token for the GET handshake
  META_WEBHOOK_SECRET  — HMAC-SHA256 key for POST signature verification
  SQS_QUEUE_URL        — target FIFO queue URL
"""

import base64
import hashlib
import hmac
import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

VERIFY_TOKEN = os.environ["META_VERIFY_TOKEN"]
WEBHOOK_SECRET = os.environ.get("META_WEBHOOK_SECRET", "")
QUEUE_URL = os.environ["SQS_QUEUE_URL"]

_sqs = boto3.client("sqs")


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    if method == "GET":
        return _handle_verify(event)
    if method == "POST":
        return _handle_event(event)
    return _resp(405, "method not allowed")


# ---------------------------------------------------------------------------
# GET — Meta webhook verification handshake
# ---------------------------------------------------------------------------

def _handle_verify(event):
    qs = event.get("queryStringParameters") or {}
    if qs.get("hub.mode") == "subscribe" and qs.get("hub.verify_token") == VERIFY_TOKEN:
        logger.info("Instagram webhook verified")
        return _resp(200, qs.get("hub.challenge", ""))
    logger.warning("Webhook verification failed — bad verify token")
    return _resp(403, "verification failed")


# ---------------------------------------------------------------------------
# POST — validate signature, fan out to SQS
# ---------------------------------------------------------------------------

def _handle_event(event):
    body = _raw_body(event)

    if not _valid_signature(body, _signature_header(event)):
        logger.warning("Invalid or missing X-Hub-Signature-256")
        return _resp(403, "invalid signature")

    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        logger.warning("Body is not valid JSON")
        return _resp(400, "bad payload")

    sent = 0
    for entry in payload.get("entry", []):
        for messaging_event in entry.get("messaging", []):
            _enqueue(messaging_event)
            sent += 1

    logger.info("Enqueued %d messaging event(s) to SQS", sent)
    # Always 200 fast — Meta retries on non-2xx, and the durable copy is in SQS.
    return _resp(200, json.dumps({"status": "ok", "enqueued": sent}))


def _enqueue(messaging_event: dict) -> None:
    """Send one messaging event to the FIFO queue.

    MessageGroupId = "{recipient}:{sender}" keeps a single conversation strictly
    ordered while letting different conversations process in parallel.
    MessageDeduplicationId = the Instagram mid (when present) collapses Meta's
    duplicate redeliveries; the queue also has content-based dedup as a fallback.
    """
    sender = messaging_event.get("sender", {}).get("id", "")
    recipient = messaging_event.get("recipient", {}).get("id", "")
    group_id = f"{recipient}:{sender}" or "unknown"

    mid = (messaging_event.get("message") or {}).get("mid")

    kwargs = {
        "QueueUrl": QUEUE_URL,
        "MessageBody": json.dumps(messaging_event),
        "MessageGroupId": group_id,
    }
    if mid:
        # Instagram mids can exceed SQS's 128-char MessageDeduplicationId limit,
        # so hash to a stable 64-char hex id (same mid → same id, so dedup still
        # collapses Meta's duplicate redeliveries).
        kwargs["MessageDeduplicationId"] = hashlib.sha256(mid.encode()).hexdigest()

    _sqs.send_message(**kwargs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw_body(event) -> bytes:
    """Return the exact bytes Meta sent — required for a correct HMAC."""
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(raw)
    return raw.encode("utf-8")


def _signature_header(event) -> str | None:
    headers = event.get("headers") or {}
    # API Gateway lowercases header names.
    return headers.get("x-hub-signature-256")


def _valid_signature(body: bytes, signature_header: str | None) -> bool:
    if not WEBHOOK_SECRET:
        logger.warning("META_WEBHOOK_SECRET not set — skipping signature check")
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    received = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)


def _resp(status: int, body: str):
    return {
        "statusCode": status,
        "headers": {"content-type": "text/plain"},
        "body": body,
    }
