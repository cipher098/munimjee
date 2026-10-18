"""Failure boundaries only; these fakes are not migrated PG/provider proof."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from app.config import settings
from app.services import activity_producers as hooks, activity_v1 as domain
from app.services.instagram_ingress import persist_message
from tests.test_instagram_ingress import message, scalar_result


class Boundary:
    def __init__(self): self.events=[]
    @asynccontextmanager
    async def begin_nested(self):
        self.events.append('savepoint')
        try:
            yield
        except BaseException:
            self.events.append('rollback-savepoint')
            raise
        else:
            self.events.append('release-savepoint')
    async def execute(self, query, params=None):
        self.events.append(str(query))
        return SimpleNamespace(one=lambda:('0','0'))


def enabled(monkeypatch):
    monkeypatch.setattr(settings,'V1_ACTIVITY_ENABLED',True)
    monkeypatch.setattr(settings,'V1_ACTIVITY_RETENTION_READY',True)


@pytest.mark.asyncio
async def test_ledger_failure_rolls_back_only_savepoint_and_logs_no_exception(monkeypatch,caplog):
    enabled(monkeypatch);db=Boundary()
    async def fail(*a,**kw):raise RuntimeError('private-token / provider-body / SQL-parameters')
    monkeypatch.setattr(domain,'record_source',fail)
    assert not await hooks.instagram_inbound(db,uuid4(),uuid4())
    assert db.events[-1]=='rollback-savepoint'
    assert 'private-token' not in caplog.text and 'SQL-parameters' not in caplog.text
    assert 'domain transaction retained' in caplog.text


@pytest.mark.asyncio
async def test_success_restores_transaction_timeouts_before_releasing_savepoint(monkeypatch):
    enabled(monkeypatch);db=Boundary();record=AsyncMock(return_value=True)
    monkeypatch.setattr(domain,'record_source',record)
    assert await hooks.whatsapp_outbound(db,uuid4(),uuid4(),hooks.AutomatedWhatsAppProducer.ORDER_UPDATE)
    assert record.call_args.kwargs=={'origin':'automated','is_new':True}
    assert 'set_config' in db.events[-2] and db.events[-1]=='release-savepoint'


@pytest.mark.asyncio
async def test_cancellation_propagates_and_never_acknowledges_unknown_domain_outcome(monkeypatch):
    enabled(monkeypatch);db=Boundary()
    async def cancel(*a,**kw):raise asyncio.CancelledError()
    monkeypatch.setattr(domain,'record_source',cancel)
    with pytest.raises(asyncio.CancelledError):await hooks.whatsapp_inbound(db,uuid4(),uuid4())
    assert db.events[-1]=='rollback-savepoint'


@pytest.mark.asyncio
async def test_default_manual_queue_origin_is_not_inferred_as_automation(monkeypatch):
    enabled(monkeypatch);db=Boundary();record=AsyncMock(return_value=True)
    monkeypatch.setattr(domain,'record_source',record)
    await hooks.whatsapp_outbound(db,uuid4(),uuid4(),None)
    assert record.call_args.kwargs['origin']=='operator'
    for fake in ('inbound_reply',True,{'automated':True}):
        with pytest.raises(ValueError):await hooks.whatsapp_outbound(db,uuid4(),uuid4(),fake)


@pytest.mark.asyncio
async def test_default_off_never_opens_a_measurement_transaction(monkeypatch):
    monkeypatch.setattr(settings,'V1_ACTIVITY_ENABLED',False)
    db=Boundary()
    assert not await hooks.comment_action(db,uuid4(),uuid4())
    assert db.events==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('new',[True,False])
async def test_instagram_duplicate_ack_does_not_backfill_measurement(monkeypatch,new):
    bid=uuid4();receipt=SimpleNamespace(seller_id=bid)
    db=SimpleNamespace(execute=AsyncMock(return_value=scalar_result([SimpleNamespace(id=bid)])),
        scalar=AsyncMock(side_effect=[uuid4() if new else None,receipt]),flush=AsyncMock(),commit=AsyncMock())
    observer=AsyncMock(return_value=False);monkeypatch.setattr(hooks,'instagram_inbound',observer)
    assert await persist_message(db,message()) is receipt
    assert observer.await_count==int(new)
    db.commit.assert_awaited_once()
