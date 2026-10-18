"""Source/pure adversarial checks. No PostgreSQL, browser or provider proof."""
import importlib.util
import io
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql

from app.models.comment_operator import CommentOperatorCommand, CommentOperatorReview, WhatsAppEnquiryReview, WhatsAppEnquiryClosure
from app.schemas.comment_operator import ReviewClose, RuleFacts
from app.services import comment_operator as domain
from app.services import whatsapp_context as context


def close_body(**changes):
    return ReviewClose(**({'idempotency_key': uuid4(), 'confirmed': True,
        'reason': 'Reviewed the original conversation', 'expected_fingerprint': 'a' * 64} | changes))


@pytest.mark.parametrize('value', [1, 0, 'true', '1', None, False])
def test_numeric_or_coerced_review_confirmation_is_not_consent(value):
    with pytest.raises(ValidationError):
        close_body(confirmed=value)


@pytest.mark.parametrize('value', ['  short  ', 'x\x00' + 'a' * 12, '\ud800' * 12])
def test_review_reason_is_encodable_and_has_actual_substance(value):
    with pytest.raises(ValidationError):
        close_body(reason=value)


def test_rule_scope_cannot_be_missing_or_numeric_boolean():
    facts = dict(name='Explicit post', enabled=False, media_id='1234', keywords=['Price'],
        product_id=uuid4(), private_reply='Our team can help', public_reply=None)
    assert RuleFacts(**facts).keywords == ['Price']
    for patch in ({'media_id': None}, {'enabled': 1}, {'private_reply': '\ud800'}, {'keywords': ['x\x00']}):
        with pytest.raises(ValidationError):
            RuleFacts(**(facts | patch))


@pytest.mark.parametrize('status,claim,attempt,provider,expected', [
    ('pending', {'v': 1}, None, None, 'not_attempted'),
    ('pending', None, None, None, 'not_confirmed'),
    ('unknown', {'v': 1}, None, None, 'not_confirmed'),
    ('sending', {'v': 1}, datetime.now(timezone.utc), None, 'not_confirmed'),
    ('sent', {'v': 1}, datetime.now(timezone.utc), 'original-receipt', 'provider_accepted'),
])
def test_legacy_or_unknown_effect_cannot_be_labelled_unattempted(status, claim, attempt, provider, expected):
    assert domain.outcome({'status': status, 'accepted_claim': claim,
        'attempted_at': attempt, 'claim_token': None, 'provider_id': provider}) == expected


def test_cursor_cannot_cross_business_kind_or_filter():
    bid = uuid4()
    row = {'id': uuid4(), 'created_at': datetime.now(timezone.utc)}
    cursor = domain.cursor_token(bid, 'events', 'open', row)
    assert domain.cursor_values(cursor, bid, 'events', 'open')[1] == row['id']
    for args in [(uuid4(), 'events', 'open'), (bid, 'enquiries', 'open'), (bid, 'events', 'closed')]:
        with pytest.raises(HTTPException) as error:
            domain.cursor_values(cursor, *args)
        assert error.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['pending', 'sending'])
async def test_close_refuses_any_active_action_without_waiting_on_action_lock(monkeypatch, status):
    monkeypatch.setattr(domain, 'access', AsyncMock())
    monkeypatch.setattr(domain, 'command_receipt', AsyncMock(return_value=('hash', None)))
    lock_calls = []
    async def one(db, model, bid, eid, *, lock=False):
        lock_calls.append((model.__name__, lock))
        return {'id': eid}
    monkeypatch.setattr(domain, 'one', one)
    monkeypatch.setattr(domain, 'actions', AsyncMock(return_value=[{'status': 'unknown'}, {'status': status}]))
    monkeypatch.setattr(domain, 'record', AsyncMock(side_effect=AssertionError('No accepted receipt for a refused close')))
    with pytest.raises(HTTPException) as error:
        await domain.close_comment(NS(), NS(user_id=uuid4()), uuid4(), uuid4(), close_body())
    assert error.value.status_code == 409
    assert error.value.detail['code'] == 'comment_operator_context_changed'
    assert lock_calls == [('CommentEvent', True)]


@pytest.mark.asyncio
async def test_exact_replay_precedes_current_snapshot_lookup(monkeypatch):
    monkeypatch.setattr(domain, 'access', AsyncMock())
    accepted = {'result': {'resource_id': str(uuid4()), 'fingerprint': 'b' * 64}, 'replayed': True}
    monkeypatch.setattr(domain, 'command_receipt', AsyncMock(return_value=('hash', accepted)))
    monkeypatch.setattr(domain, 'one', AsyncMock(side_effect=AssertionError('Old accepted command must not inspect a changed snapshot')))
    assert await domain.close_comment(NS(), NS(user_id=uuid4()), uuid4(), uuid4(), close_body()) == accepted


@pytest.mark.asyncio
async def test_unknown_close_appends_review_without_relabelling_effect(monkeypatch):
    monkeypatch.setattr(domain, 'access', AsyncMock())
    monkeypatch.setattr(domain, 'command_receipt', AsyncMock(return_value=('hash', None)))
    event = {'id': uuid4()}
    action = {'id': uuid4(), 'status': 'unknown', 'provider_id': None}
    monkeypatch.setattr(domain, 'one', AsyncMock(return_value=event))
    monkeypatch.setattr(domain, 'actions', AsyncMock(return_value=[action]))
    monkeypatch.setattr(domain, 'record', AsyncMock(return_value=(NS(id=uuid4()), {'accepted': True})))
    rows = []
    db = NS(scalar=AsyncMock(return_value=None), flush=AsyncMock(), add=rows.append)
    result = await domain.close_comment(db, NS(user_id=uuid4()), uuid4(), event['id'],
        close_body(expected_fingerprint=domain.event_fingerprint(event, [action])))
    assert result == {'accepted': True}
    assert len(rows) == 1 and isinstance(rows[0], CommentOperatorReview)
    assert action['status'] == 'unknown' and action['provider_id'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('source,activated,match,expected', [
    ('recent_message', True, True, 'activated_inferred_context'),
    ('recent_message', True, False, None),
    ('unverified_source', True, True, None),
    ('message_link', True, True, None),
])
async def test_only_exact_activated_inferred_case_produces_manual_enquiry(monkeypatch, source, activated, match, expected):
    from app.services import sku_fact_replies as facts
    product_id = uuid4()
    monkeypatch.setattr(facts, 'enabled', lambda: True)
    monkeypatch.setattr(facts, 'exact_reel_products', AsyncMock(return_value=[product_id] if match else []))
    monkeypatch.setattr(facts, 'is_activated', AsyncMock(return_value=activated))
    monkeypatch.setattr(facts, 'read_facts', AsyncMock(return_value=None))
    payload = {'source': source, 'references': [{'status': 'matched', 'url': 'https://www.instagram.com/reel/Synthetic/',
        'products': [{'id': str(product_id)}]}]}
    decision = await context.reel_reply_decision(NS(), uuid4(), payload, 'price?')
    assert decision.reply is None and decision.review_reason == expected
    assert await context.reel_catalogue_reply(NS(), uuid4(), payload, 'price?') is None


def test_schema_static_migration_and_model_constraints_match_without_db():
    path = Path(__file__).parents[1] / 'alembic/versions/0056_v1_comment_operator.py'
    spec = importlib.util.spec_from_file_location('comment_operator_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == '0055_v1_comment_binding'
    output = io.StringIO()
    migration = MigrationContext.configure(dialect_name='postgresql', opts={'as_sql': True, 'output_buffer': output})
    with Operations.context(migration):
        module.upgrade()
    sql = output.getvalue()
    assert 'NOT VALID' not in sql and 'CREATE TRIGGER' in sql
    for model in (CommentOperatorCommand, CommentOperatorReview, WhatsAppEnquiryReview, WhatsAppEnquiryClosure):
        table = model.__table__
        assert 'CREATE TABLE ' + table.name in sql
        for constraint in table.constraints:
            if constraint.name:
                assert constraint.name in sql
        assert all(index.name in sql for index in table.indexes)
        assert 'FOREIGN KEY' in str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert 'phone_number_id' in sql and 'wa_message_review_source' in sql


def test_legacy_rule_delete_stays_disable_instead_of_clearing_immutable_event_fk():
    import ast
    source = Path(__file__).parents[1] / 'app/api/routes/comment_automation.py'
    node = next(node for node in ast.parse(source.read_text()).body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'delete_rule')
    assert 'rule.enabled = False' in ast.unparse(node)
    assert not any(isinstance(item, ast.Attribute) and item.attr == 'delete' for statement in node.body for item in ast.walk(statement))


def test_native_router_imports_without_provider_or_db_and_never_exposes_resend_endpoint():
    from app.api.v1.comment_operator import router
    paths = [route.path for route in router.routes]
    assert '/api/v1/businesses/{business_id}/comment-automation/events/{event_id}/reviews' in paths
    assert '/api/v1/businesses/{business_id}/whatsapp/enquiries/{enquiry_id}/close' in paths
    assert not any(part in path for path in paths for part in ('resend', 'replay', 'rebind', 'mark-delivered'))
