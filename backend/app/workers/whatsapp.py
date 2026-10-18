"""Durable outbox scanner. Crashed/ambiguous sends require review, never blind retry."""
import asyncio
from datetime import timedelta
from sqlalchemy import select, update
from fastapi import HTTPException
from app.database import worker_session
from app.models.whatsapp import WhatsAppMessage, WhatsAppTemplate
from app.services import whatsapp as service, whatsapp_provider as provider
from app.workers.celery_app import celery_app


async def deliver_one(message_id, session_factory=worker_session):
    # Commit claim BEFORE contacting Meta: worker crash cannot blindly resend.
    async with session_factory() as db:
        message = await db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.id == message_id,WhatsAppMessage.status == 'queued').with_for_update(skip_locked=True))
        if not message:
            return
        message.status, message.updated_at = 'sending', service.now()
        seller_id, contact_id = message.seller_id, message.contact_id
        await db.commit()
    async with session_factory() as db:
        try:
            account = await service.account_for(db,seller_id,lock=True)
            contact = await service.contact_for(db,seller_id,contact_id,lock=True)
            message = await db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.id == message_id).with_for_update())
            if message.status != 'sending':
                return
            if contact.opted_out or message.phone_number_id != account.phone_number_id:
                raise HTTPException(409,'Contact opted out or WhatsApp account changed')
            # Only a current immutable exact Message FK can permit this fixed
            # owner/recipient-authorized reply while general sending is paused.
            # The helper's final coherent scalar check is the last await for a
            # valid fixed text before provider.send; ordinary paths stay gated.
            from app.services.whatsapp_test_authority import exact_test_authority
            test_authority = await exact_test_authority(db, account, contact, message)
            if test_authority is None and not account.enabled:
                raise HTTPException(409,'Connect and enable WhatsApp first')
            if message.idempotency_key.startswith('auto:') and not account.automation_enabled:
                raise HTTPException(409,'Automation was disabled before delivery')
            if message.idempotency_key.startswith('auto:reel:'):
                if not account.reel_replies_enabled:
                    raise HTTPException(409, 'Reel replies were disabled before delivery')
                # Recheck current mapping, active state and listed price at send time.
                refreshed = await service.reel_catalogue_reply(db, seller_id,
                    message.payload.get('reel_context', {}), message.payload.get('customer_text', ''))
                if not refreshed:
                    raise HTTPException(409, 'Reel product changed or became unavailable before delivery')
                message.text = refreshed
            if message.kind == 'template':
                # Refresh approval immediately before send; stale approvals never authorize sending.
                await service.sync_templates(db,account)
                template = await db.scalar(select(WhatsAppTemplate).where(WhatsAppTemplate.seller_id == seller_id,WhatsAppTemplate.name == message.payload['name'],WhatsAppTemplate.language == message.payload['language']))
                if message.idempotency_key.startswith(('order:', 'parcel:')) and (not template or template.category != 'UTILITY'):
                    raise HTTPException(409,'Order updates require an approved utility template')
                service.check_template(template,contact,message.payload.get('parameters',[]))
            elif not service.window_open(contact):
                raise HTTPException(409,'The 24-hour reply window expired before delivery')
            if message.idempotency_key.startswith('parcel:'):
                from app.services.parcel_tracking import revalidate_notification
                await revalidate_notification(db, message, contact)
            provider_id = await provider.send(account,contact,message)
            message.provider_message_id, message.status, message.error = provider_id,'accepted',None
        except provider.SendUncertain as error:
            message = await db.get(WhatsAppMessage,message_id)
            message.status, message.error = 'unknown',str(error)
        except HTTPException as error:
            message = await db.get(WhatsAppMessage,message_id)
            message.status, message.error = 'failed',str(error.detail)[:500]
        await db.commit()


async def drain(session_factory=worker_session):
    async with session_factory() as db:
        await db.execute(update(WhatsAppMessage).where(WhatsAppMessage.status == 'sending',WhatsAppMessage.updated_at < service.now()-timedelta(minutes=10)).values(status='unknown',error='Worker stopped during delivery; review before sending again'))
        ids = (await db.scalars(select(WhatsAppMessage.id).where(WhatsAppMessage.direction == 'outbound',WhatsAppMessage.status == 'queued').order_by(WhatsAppMessage.created_at).limit(100))).all()
        await db.commit()
    for message_id in ids:
        await deliver_one(message_id,session_factory)


@celery_app.task(name='app.workers.whatsapp.drain_outbox')
def drain_outbox():
    asyncio.run(drain())


async def cleanup_setup_secrets(session_factory=worker_session):
    # Cleanup is deliberately independent of rollout/collection flags. It only
    # clears due provisional ciphertext; claimed/unknown phone effects remain.
    from app.services.whatsapp_self_service import cleanup_provisional
    async with session_factory() as db:
        count = await cleanup_provisional(db, limit=100)
        await db.commit()
        return count


@celery_app.task(name='app.workers.whatsapp.cleanup_setup_secrets')
def cleanup_setup_secrets_task():
    return asyncio.run(cleanup_setup_secrets())
