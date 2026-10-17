"""Pure and fake-session checks: these never connect to a database/provider."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.instagram_ingress import event_key, normalize_message, persist_message, replay_receipt


def message(**updates):
    event = {"sender": {"id": "customer"}, "recipient": {"id": "account"},
             "timestamp": 123456, "message": {"mid": "m1", "text": "price?"}}
    event.update(updates)
    return event


def test_normalization_whitelists_consumed_fields():
    event = message(seller_id="attacker", access_token="secret")
    event["message"]["authorization"] = "secret"
    assert normalize_message(event) == [{"type": "text", "text": "price?", "reply_to_mid": None, "mid": "m1"}]


def test_mid_deduplication_does_not_depend_on_rotating_media_url():
    first = message(message={"mid": "m1", "attachments": [{"type": "image", "payload": {"url": "https://example.com/a"}}]})
    second = deepcopy(first)
    second["message"]["attachments"][0]["payload"]["url"] += "?token=rotated"
    assert event_key(first, normalize_message(first)) == event_key(second, normalize_message(second))


def test_fallback_key_is_stable_and_distinguishes_timestamp():
    first = message(message={"text": "price?"})
    assert event_key(first, normalize_message(first)) == event_key(deepcopy(first), normalize_message(first))
    second = {**first, "timestamp": 123457}
    assert event_key(first, normalize_message(first)) != event_key(second, normalize_message(second))


def test_attachment_precedence_and_multiple_attachments_match_legacy():
    event = message(message={"mid": "m", "text": "caption", "attachments": [
        {"type": "image", "payload": {"url": "https://example.com/image"}},
        {"type": "share", "payload": {"link": "https://instagram.com/reel/x", "title": "item"}},
    ]})
    assert [row["type"] for row in normalize_message(event)] == ["image", "reel"]


def test_echo_and_non_actionable_do_not_enter_inbox():
    assert normalize_message(message(message={"is_echo": True, "text": "echo"})) == []
    assert normalize_message(message(message={"mid": "m"})) == []


def scalar_result(rows):
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


@pytest.mark.asyncio
async def test_persist_binds_from_database_and_commits_before_return():
    seller_id = uuid4()
    receipt = SimpleNamespace(seller_id=seller_id)
    db = SimpleNamespace(execute=AsyncMock(side_effect=[scalar_result([SimpleNamespace(id=seller_id)]), None]),
                         scalar=AsyncMock(return_value=receipt), commit=AsyncMock())
    assert await persist_message(db, message(seller_id=str(uuid4()))) is receipt
    values = db.execute.call_args_list[1].args[0].compile().params
    assert values["seller_id"] == seller_id
    assert values["account_id"] == "account"
    assert "secret" not in str(values)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_database_failure_is_not_acknowledged():
    db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("offline")), commit=AsyncMock())
    with pytest.raises(RuntimeError):
        await persist_message(db, message())
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_ambiguous_account_is_rejected_before_insert():
    db = SimpleNamespace(execute=AsyncMock(return_value=scalar_result([SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())])))
    with pytest.raises(ValueError, match="ambiguous_instagram_account"):
        await persist_message(db, message())
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_unknown_effect_replay_requires_explicit_review():
    row = SimpleNamespace(status="error", error_code="processing_interrupted_unknown_effect")
    db = SimpleNamespace(scalar=AsyncMock(return_value=row))
    with pytest.raises(ValueError, match="side_effect_review_required"):
        await replay_receipt(db, uuid4(), uuid4())
    assert row.status == "error"


@pytest.mark.asyncio
async def test_reviewed_replay_rechecks_binding_and_becomes_retry():
    row = SimpleNamespace(status="error", error_code="processing_failed_unknown_effect", seller_id=uuid4(), account_id="account")
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[row, SimpleNamespace()]), flush=AsyncMock())
    assert await replay_receipt(db, uuid4(), row.seller_id, side_effects_reviewed=True)
    assert row.status == "retry"
    assert row.error_code is None
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_replay_cannot_transfer_receipt_after_account_disconnect():
    row = SimpleNamespace(status="error", error_code="instagram_account_binding_changed", seller_id=uuid4(), account_id="account")
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[row, None]))
    with pytest.raises(ValueError, match="instagram_account_binding_changed"):
        await replay_receipt(db, uuid4(), row.seller_id)
