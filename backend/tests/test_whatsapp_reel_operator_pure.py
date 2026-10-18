"""Frozen18 pure A13 checks. No SQL/provider/native-session proof is claimed.

Raw projection results replace only declared repository boundaries. Dispatch
adapter checks remain adapters until the integrator installs the real sender
seam. Actual database acceptance is authored separately and is never run here.
"""
from tests.safety import install_test_safety

install_test_safety()

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.whatsapp_reel_operator import LinkCommand


BID = UUID("10000000-0000-4000-8000-000000000101")
MID = UUID("20000000-0000-4000-8000-000000000101")
PID = UUID("30000000-0000-4000-8000-000000000101")
KEY = UUID("40000000-0000-4000-8000-000000000101")
CID = UUID("50000000-0000-4000-8000-000000000101")
OUT = UUID("60000000-0000-4000-8000-000000000101")
UID = UUID("70000000-0000-4000-8000-000000000101")
SID = UUID("80000000-0000-4000-8000-000000000101")
CONTACT = UUID("90000000-0000-4000-8000-000000000101")


def command_body(action="link_and_resume"):
    return {"idempotency_key": str(KEY), "action": action, "product_id": str(PID), "shortcode": "Case_Ab-1",
            "expected_fingerprint": "a" * 64, "expected_connection_version": 3, "confirmed": True}


@pytest.mark.parametrize("action", ["link_only", "link_and_resume"])
def test_p01_only_two_single_source_actions_have_exact_seven_field_body(action):
    result = LinkCommand.model_validate(command_body(action)).model_dump(mode="json")
    assert result == command_body(action)


@pytest.mark.parametrize("field", ["recipient", "source", "reviewer"])
def test_p02_caller_authority_fields_are_rejected(field):
    with pytest.raises(ValidationError):
        LinkCommand.model_validate({**command_body(), field: "untrusted-caller-assertion"})


def test_p03_numeric_confirmation_cannot_authorize_a_command():
    with pytest.raises(ValidationError):
        LinkCommand.model_validate({**command_body(), "confirmed": 1})


def test_p04_bulk_or_unrecognized_action_is_not_single_enquiry_consent():
    with pytest.raises(ValidationError):
        LinkCommand.model_validate({**command_body(), "action": "bulk_resume"})

from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint
from app.schemas.sku_fact_replies import ProductFacts, SKUFact
from app.services import whatsapp_reel_operator as service
from app.models.whatsapp_reel_operator import WhatsAppReelCommand, WhatsAppReelAuthorization


class Boundary:
    """Strict call-order boundary, not a SQL evaluator or persistence substitute."""
    def __init__(self, receipt=None):
        self.receipt = receipt
        self.calls = []

    async def execute(self, statement, params=None):
        assert len(self.calls) == 0, "unexpected repository execute"
        assert "pg_advisory_xact_lock" in str(statement)
        assert params == {"scope": f"native-reel-command:{BID}:{KEY}"}
        self.calls.append("lock")

    async def scalar(self, statement):
        assert self.calls == ["lock"]
        assert "whatsapp_reel_commands" in str(statement)
        assert statement.compile().params == {"business_id_1": BID, "idempotency_key_1": KEY}
        self.calls.append("receipt_lookup")
        return self.receipt


def saved_receipt():
    return SimpleNamespace(id=CID, business_id=BID, inbound_message_id=MID, idempotency_key=KEY,
        action="link_and_resume", product_id=PID, actor_user_id=UID, actor_session_id=SID,
        actor_auth_version=4, request_hash=service.request_hash(BID, MID, LinkCommand(**command_body())),
        result={"mapping": "saved", "resume": "queued", "reason": None, "outbound_id": str(OUT),
                "mapping_fingerprint": "c" * 64})


def replay_setup(monkeypatch, row):
    db = Boundary(row)
    actor = SimpleNamespace(user_id=UID, auth_method="v1_user")
    binding = service.ReviewerBinding(UID, SID, 4)
    events = []
    async def access(*args, **kwargs):
        assert kwargs == {"write": True}
        events.append("access")
    async def authority():
        events.append("authority")
        return binding
    monkeypatch.setattr(service, "access", access)
    async def forbidden(*args, **kwargs):
        raise AssertionError("replay must not reread or mutate source")
    monkeypatch.setattr(service, "source_row", forbidden)
    return db, actor, authority, events


@pytest.mark.asyncio
async def test_p05_exact_replay_looks_up_saved_receipt_before_source_and_rechecks_authority(monkeypatch):
    db, actor, authority, events = replay_setup(monkeypatch, saved_receipt())
    result = await service.link_enquiry(db, actor, BID, MID, LinkCommand(**command_body()), request_authority=authority)
    assert result["replayed"] is True and result["command_id"] == str(CID)
    assert result["result"]["outbound_id"] == str(OUT)
    assert db.calls == ["lock", "receipt_lookup"]
    assert events == ["access", "authority"] * 3


@pytest.mark.asyncio
async def test_p06_replay_requires_current_exact_session_after_lock(monkeypatch):
    db, actor, authority, events = replay_setup(monkeypatch, saved_receipt())
    count = 0
    async def changed():
        nonlocal count
        count += 1
        return service.ReviewerBinding(UID, SID if count == 1 else OUT, 4)
    with pytest.raises(HTTPException) as caught:
        await service.link_enquiry(db, actor, BID, MID, LinkCommand(**command_body()), request_authority=changed)
    assert caught.value.status_code == 401
    assert db.calls == ["lock"]  # no receipt exposure under replacement session


@pytest.mark.asyncio
async def test_p07_same_key_changed_body_is_unclassified_conflict_and_not_safe_to_discard(monkeypatch):
    db, actor, authority, events = replay_setup(monkeypatch, saved_receipt())
    body = {**command_body(), "action": "link_only"}
    with pytest.raises(HTTPException) as caught:
        await service.link_enquiry(db, actor, BID, MID, LinkCommand(**body), request_authority=authority)
    assert caught.value.status_code == 409 and isinstance(caught.value.detail, str)
    assert db.calls == ["lock", "receipt_lookup"]


@pytest.mark.asyncio
async def test_p08_typed_pre_effect_rejection_follows_absent_receipt_lookup(monkeypatch):
    db, actor, authority, events = replay_setup(monkeypatch, None)
    async def source(*args, **kwargs):
        assert db.calls == ["lock", "receipt_lookup"] and not kwargs
        db.calls.append("source")
        return SimpleNamespace(contact_id=CONTACT), "d" * 64
    async def scalar(statement):
        if db.calls == ["lock"]:
            return await Boundary.scalar(db, statement)
        assert db.calls == ["lock", "receipt_lookup", "source"]
        assert "whatsapp_accounts" in str(statement) and "FOR UPDATE" in str(statement)
        db.calls.append("account_missing")
        return None
    monkeypatch.setattr(service, "source_row", source)
    db.scalar = scalar
    with pytest.raises(HTTPException) as caught:
        await service.link_enquiry(db, actor, BID, MID, LinkCommand(**command_body()), request_authority=authority)
    assert caught.value.status_code == 409
    assert caught.value.detail == {"code": "reel_operator_pre_mutation_rejection", "business_id": str(BID),
        "inbound_id": str(MID), "idempotency_key": str(KEY), "request_hash": saved_receipt().request_hash,
        "accepted": False, "reason": "account_unavailable"}
    assert db.calls == ["lock", "receipt_lookup", "source", "account_missing"]


def observations():
    return ProductFacts(business_id=BID, product_id=PID, product_name="Reviewed cotton kurta", mapping_revision=7,
        observed_at=datetime(2026, 10, 18, tzinfo=timezone.utc), fact_hash="d" * 64,
        skus=(SKUFact(sku_id=KEY, options={"Size": "M"}, price_minor=12345, currency="INR", stock_available=0),))


class HelperBoundary:
    def __init__(self, accepted, allowed=OUT):
        self.accepted, self.allowed, self.calls = accepted, allowed, []
    async def execute(self, query):
        assert self.calls == []
        assert "whatsapp_reel_authorizations.outbound_message_id" in str(query)
        assert query.compile().params == {"outbound_message_id_1": OUT}
        self.calls.append("lookup")
        return SimpleNamespace(scalar_one_or_none=lambda: self.accepted)
    async def flush(self):
        assert self.calls == ["lookup", "read_facts"]
        self.calls.append("flush")
    async def scalar(self, query, params):
        assert self.calls == ["lookup", "read_facts", "flush"]
        assert str(query) == service.FINAL_RESUME_SQL
        assert params["outbound_id"] == OUT and params["business_id"] == BID and params["contact_id"] == CONTACT
        assert params["product_name"] == "Reviewed cotton kurta" and params["mapping_revision"] == 7
        assert params["expected_text"] == "Current catalogue: Reviewed cotton kurta.\n• Size: M — ₹123.45; recorded out of stock.\nAvailability is a current catalogue observation, not a reservation. Please confirm your preferred option with our team."
        import json
        assert json.loads(params["expected_skus"]) == [{"sku_id": str(KEY), "options": {"Size": "M"},
            "price_minor": 12345, "currency": "INR", "stock_available": 0}]
        self.calls.append("final_scalar")
        return self.allowed


def helper_setup(monkeypatch, accepted=True, allowed=OUT):
    row = SimpleNamespace(business_id=BID, contact_id=CONTACT, product_id=PID,
        source_url="https://www.instagram.com/reel/Case_Ab-1/", shortcode="Case_Ab-1") if accepted else None
    db = HelperBoundary(row, allowed)
    async def read(db_arg, business, product, *, reel):
        assert db_arg is db and (business, product) == (BID, PID)
        assert reel == {"reel_url": "https://www.instagram.com/reel/Case_Ab-1/"}
        assert db.calls == ["lookup"]
        db.calls.append("read_facts")
        return observations()
    monkeypatch.setattr(service.settings, "V1_AUTH_ENABLED", True)
    monkeypatch.setattr(service.facts, "enabled", lambda: True)
    from app.services import whatsapp_test_authority
    async def legacy_guard(*values):
        assert values == (db, account, contact, message)
        assert db.calls == ["lookup"]
        db.calls.append("incumbent_final_guard")
        return object()  # never used as a boolean send exception
    monkeypatch.setattr(whatsapp_test_authority, "exact_test_authority", legacy_guard)
    monkeypatch.setattr(service.facts, "read_facts", read)
    account, contact, message = SimpleNamespace(seller_id=BID), SimpleNamespace(id=CONTACT), SimpleNamespace(
        id=OUT, seller_id=BID, text="stale draft", payload={"customer_text": "price and sizes?"})
    return db, account, contact, message


@pytest.mark.asyncio
async def test_p09_ordinary_canonical_outbox_without_authorization_returns_none(monkeypatch):
    values = helper_setup(monkeypatch, accepted=False)
    assert await service.revalidate_resume(*values) is None
    assert values[0].calls == ["lookup", "incumbent_final_guard"] and values[3].text == "stale draft"


@pytest.mark.asyncio
async def test_p10_bound_valid_helper_regenerates_actual_facts_then_final_scalar_returns_none(monkeypatch):
    values = helper_setup(monkeypatch)
    assert await service.revalidate_resume(*values) is None
    assert values[0].calls == ["lookup", "read_facts", "flush", "final_scalar"]
    assert "₹123.45" in values[3].text and "recorded out of stock" in values[3].text


@pytest.mark.asyncio
async def test_p11_bound_invalid_final_scalar_raises_409_without_boolean_authority(monkeypatch):
    values = helper_setup(monkeypatch, allowed=None)
    with pytest.raises(HTTPException) as caught:
        await service.revalidate_resume(*values)
    assert caught.value.status_code == 409 and values[0].calls[-1] == "final_scalar"


async def dispatch_adapter(values, sender):
    """Declared control-flow adapter: NOT the production deliver_one installation."""
    await service.revalidate_resume(*values)
    await sender()


@pytest.mark.asyncio
async def test_p12_adapter_none_is_success_not_a_false_permission_denial(monkeypatch):
    values = helper_setup(monkeypatch, accepted=False)
    sender = AsyncMock()
    await dispatch_adapter(values, sender)
    sender.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_p13_adapter_bound_invalid_409_never_reaches_sender(monkeypatch):
    values = helper_setup(monkeypatch, allowed=None)
    sender = AsyncMock()
    with pytest.raises(HTTPException):
        await dispatch_adapter(values, sender)
    sender.assert_not_awaited()


def test_p14_safe_receipt_is_bounded_and_has_no_private_authority_projection():
    row = saved_receipt()
    row.credential_fingerprint = "private credential digest"
    row.provider_mid = "private provider receipt"
    row.reply_context = {"private": "original payload"}
    result = service.receipt_view(row)
    assert set(result) == {"business_id", "inbound_id", "command_id", "idempotency_key", "action", "product_id", "request_hash", "result", "replayed"}
    assert result == {"business_id": str(BID), "inbound_id": str(MID), "command_id": str(CID), "idempotency_key": str(KEY),
        "action": "link_and_resume", "product_id": str(PID), "request_hash": "f405d03c364dedbabcac1f1fd9d4598ced7f513f0205edd99aed98d72d50190a",
        "result": {"mapping": "saved", "resume": "queued", "reason": None, "outbound_id": str(OUT), "mapping_fingerprint": "c" * 64}, "replayed": False}
    import json
    assert len(json.dumps(result)) < 2048 and "private" not in json.dumps(result)


def test_p15_model_and_migration_keep_mandatory_exact_tenant_outbound_binding_and_immutable_rows():
    command, auth = WhatsAppReelCommand.__table__, WhatsAppReelAuthorization.__table__
    assert all(not auth.c[name].nullable for name in ("command_id", "business_id", "inbound_message_id", "contact_id", "phone_number_id", "outbound_message_id"))
    expected = {"wa_reel_auth_command": ("business_id", "command_id"), "wa_reel_auth_source": ("business_id", "inbound_message_id", "contact_id", "phone_number_id"),
                "wa_reel_auth_outbound": ("business_id", "outbound_message_id", "contact_id", "phone_number_id")}
    assert {fk.name: tuple(fk.column_keys) for fk in auth.constraints if isinstance(fk, ForeignKeyConstraint)} == expected
    assert {tuple(c.columns.keys()) for c in auth.constraints if isinstance(c, UniqueConstraint)} == {("business_id", "outbound_message_id"), ("business_id", "inbound_message_id")}
    assert all(not command.c[name].nullable for name in ("actor_user_id", "actor_session_id", "actor_auth_version", "source_fingerprint", "recipient_fingerprint", "accepted_mapping_fingerprint"))
    source = (Path(__file__).parents[1] / "alembic/versions/0058_v1_reel_operator.py").read_text()
    assert "down_revision = '0057_v1_whatsapp_self_service'" in source
    for literal in ("BEFORE UPDATE OR DELETE ON ", "wa_reel_immutable", "wa_reel_auth_outbound", "wa_reel_command_source"):
        assert literal in source
