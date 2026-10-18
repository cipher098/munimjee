"""Best-effort measurement of already flushed, newly accepted domain rows.

Callers own their receipt/outbox transaction. No network or commit lives here.
The savepoint confines a ledger failure to instrumentation; domain flush errors
must happen BEFORE this seam and are never swallowed by it.
"""
import logging
from enum import Enum
from sqlalchemy import text
from app.config import settings

logger = logging.getLogger(__name__)


class AutomatedWhatsAppProducer(Enum):
    INBOUND_REPLY = 'inbound_reply'
    REEL_REVIEW = 'reel_review'
    ORDER_UPDATE = 'order_update'
    PARCEL_UPDATE = 'parcel_update'


async def _observe(db, business_id, source_kind, source_id, origin):
    if not (settings.V1_ACTIVITY_ENABLED and settings.V1_ACTIVITY_RETENTION_READY):
        return False
    from app.services.activity_v1 import record_source
    try:
        async with db.begin_nested():
            # Instrumentation must not wait indefinitely on owner policy or
            # maintenance locks while the durable ingress/outbox awaits ack.
            previous = (await db.execute(text("SELECT current_setting('lock_timeout'), current_setting('statement_timeout')"))).one()
            await db.execute(text("SELECT set_config('lock_timeout','100ms',true), set_config('statement_timeout','250ms',true)"))
            recorded = await record_source(db, business_id, source_kind, source_id,
                origin=origin, is_new=True)
            await db.execute(text("SELECT set_config('lock_timeout',:lock,true), set_config('statement_timeout',:statement,true)"),
                {'lock': previous[0], 'statement': previous[1]})
            return recorded
    except Exception:
        # Never print exception/SQL/parameters, source identity or message data.
        # Cancellation is BaseException and deliberately still propagates.
        logger.warning('Activity observation unavailable; domain transaction retained')
        return False


async def instagram_inbound(db, business_id, source_id):
    return await _observe(db, business_id, 'instagram_ingress', source_id, 'inbound')


async def whatsapp_inbound(db, business_id, source_id):
    return await _observe(db, business_id, 'wa_inbound', source_id, 'inbound')


async def whatsapp_outbound(db, business_id, source_id, producer):
    # Only enumerated, explicitly wired internal producers authorize automation
    # classification. Manual queue users supply no marker and remain unknown.
    if producer is not None and not isinstance(producer, AutomatedWhatsAppProducer):
        raise ValueError('Unsupported internal WhatsApp measurement producer')
    return await _observe(db, business_id, 'wa_outbound', source_id,
        'automated' if producer is not None else 'operator')


async def comment_action(db, business_id, source_id):
    return await _observe(db, business_id, 'comment_action', source_id, 'automated')
