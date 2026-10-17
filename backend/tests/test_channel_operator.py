"""Pure channel operator contracts; no provider, database or send access."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.schemas.channel_operator import Review, WhatsAppConnect
from app.services.channel_operator import receipt_view
from app.services.instagram_ingress import provider_event_time


def test_review_requires_plain_explicit_review_and_current_version():
    value = Review(idempotency_key=uuid4(), decision="resolve", reviewed=True,
                   reason="Checked the original Instagram conversation.", expected_updated_at=datetime.now(timezone.utc))
    assert value.decision == "resolve"
    with pytest.raises(ValidationError):
        Review(**{**value.model_dump(), "actor_user_id": str(uuid4())})
    with pytest.raises(ValidationError):
        Review(**{**value.model_dump(), "reason": "    "})


def test_receipt_public_view_never_leaks_media_capabilities_or_claims_delivery():
    row = SimpleNamespace(id=uuid4(), customer_id="synthetic-customer", status="resolved", error_code="reviewed_without_replay",
          events=[{"type":"image", "image_url":"https://example.invalid/media?access_token=secret"}, {"type":"text", "text":"<script>customer</script>"}],
          created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc), occurred_at=None,
          attempts=1, processed_indices=[])
    data = receipt_view(row, detail=True)
    assert data["delivery_confirmed"] is False
    assert "access_token" not in str(data) and "image_url" not in str(data)
    assert data["components"][1]["text"] == "<script>customer</script>"  # UI renders via textContent.
    assert data["customer_ref"] == "stomer"


@pytest.mark.parametrize("invalid", [None, "timestamp", True, [], {}, -1e30])
def test_unknown_provider_time_is_not_replaced_with_receipt_time(invalid):
    assert provider_event_time(invalid) is None


def test_signed_millisecond_provider_timestamp_is_preserved():
    expected = datetime(2026,10,17,10,0,tzinfo=timezone.utc)
    assert provider_event_time(expected.timestamp() * 1000) == expected


def test_connect_payload_never_accepts_tenant_or_approval_claims():
    with pytest.raises(ValidationError):
        WhatsAppConnect(idempotency_key=uuid4(), phone_number_id="123",waba_id="456",access_token="synthetic-token",
                        business_id=str(uuid4()), provider_approved=True)


def test_provider_url_logging_redacts_oauth_secrets():
    import logging
    from app.integrations.instagram import _CredentialURLFilter
    record=logging.LogRecord("httpx",logging.INFO,"synthetic",1,"HTTP Request: %s %s %s",(
        "GET","https://graph.instagram.com/access_token?access_token=synthetic-secret&client_secret=synthetic-client&fields=id","200"),None)
    assert _CredentialURLFilter().filter(record)
    message=record.getMessage()
    assert "synthetic-secret" not in message and "synthetic-client" not in message and "fields=id" in message


def test_inbound_callback_access_log_redacts_code_and_state():
    import logging
    from app.integrations.instagram import _CredentialURLFilter
    record=logging.LogRecord("uvicorn.access",logging.INFO,"synthetic",1,'%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1","GET","/api/v1/businesses/synthetic/channels/instagram/callback?code=synthetic-private-code&state=synthetic-private-state","1.1",303),None)
    assert _CredentialURLFilter().filter(record)
    message=record.getMessage()
    assert "synthetic-private-code" not in message and "synthetic-private-state" not in message and "callback" in message
