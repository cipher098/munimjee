"""Actual shared app.main; synthetic fixture facts/transports, ephemeral local TLS.

Never imported by production. Native routes are not manually mounted here.
"""
from tests.safety import install_test_safety
install_test_safety()

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import sys
import httpx
from fastapi import Depends
from sqlalchemy import func, select, update

from app.config import settings
settings.V1_AUTH_ENABLED = True
settings.V1_ENFORCE_LEGACY_ACCESS = True
settings.V1_SKU_FACT_REPLIES_ENABLED = True
settings.PUBLIC_BASE_URL = 'https://127.0.0.1:8156'
settings.META_WEBHOOK_SECRET = settings.WHATSAPP_APP_SECRET = 'synthetic-operator-signature'
from app.main import app
from app.api.v1.session import require_v1_mutation
from app.database import get_db
from app.models.identity import Membership
from app.models.seller import Seller
from app.models.product import Product
from app.models.commerce import Storefront
from app.models.catalogue_v1 import CatalogueProductMapping, CatalogueSKU
from app.models.checkout_v1 import CatalogueActivation
from app.models.channel_operator import ChannelConnectionState
from app.models.comment_automation import CommentAction, CommentEvent, CommentRule
from app.models.comment_operator import CommentOperatorCommand, CommentOperatorReview, WhatsAppEnquiryReview, WhatsAppEnquiryClosure
from app.models.whatsapp import WhatsAppAccount, WhatsAppMessage
from app.services.identity import require_business_access
from app.integrations.instagram import InstagramClient
from app.services import whatsapp_provider
from app.workers.comment_automation import dispatch_one

attempts = []


async def private_result(client, comment_id, body):
    attempts.append({'channel': 'instagram', 'kind': 'private', 'account': client.fb_page_id})
    raise httpx.ReadTimeout('Synthetic unconfirmed provider result; no network')


async def public_result(client, comment_id, body):
    attempts.append({'channel': 'instagram', 'kind': 'public', 'account': client.fb_page_id})
    return {'id': 'synthetic-public-' + uuid4().hex}


async def unexpected_whatsapp_send(*args):
    attempts.append({'channel': 'whatsapp', 'kind': 'unexpected'})
    raise AssertionError('No WhatsApp provider call is part of this operator fixture')


InstagramClient.send_private_reply = private_result
InstagramClient.reply_to_comment = public_result
whatsapp_provider.send = unexpected_whatsapp_send


@app.post('/__test/comment-operator/{business_id}/seed')
async def seed(business_id: UUID, actor=Depends(require_v1_mutation), db=Depends(get_db)):
    await require_business_access(db, actor, business_id, 'channels.connect')
    account, phone, waba = (str(uuid4().int)[:15] for _ in range(3))
    legacy, activated = uuid4(), uuid4()
    await db.execute(update(Seller).where(Seller.id == business_id).values(instagram_id=account,
        instagram_page_id=account, instagram_token='synthetic-operator-never-provider',
        instagram_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
    db.add_all([Storefront(seller_id=business_id, slug='operator-' + uuid4().hex, name='Synthetic operator boutique', published=True),
        Product(id=legacy, seller_id=business_id, name='Synthetic linen dress', active=True, listed_price=12345, floor_price=4000),
        Product(id=activated, seller_id=business_id, name='Synthetic reviewed saree', active=True, listed_price=999999, floor_price=4000,
            reel_urls=['https://www.instagram.com/reel/Operator_saree/']),
        ChannelConnectionState(business_id=business_id, channel='instagram', version=1, provider_account_id=account,
            automation_enabled=True, check_status='verified', checked_at=datetime.now(timezone.utc)),
        WhatsAppAccount(seller_id=business_id, phone_number_id=phone, waba_id=waba, access_token='synthetic-not-decrypted',
            enabled=True, automation_enabled=True, reel_replies_enabled=True)])
    await db.flush()
    db.add_all([CommentRule(seller_id=business_id, name='Synthetic unconfirmed reply', enabled=True, media_id='300', keywords=['price'],
            product_id=legacy, private_reply='Our team can help with this dress.', public_reply='Please check your inbox.'),
        CommentRule(seller_id=business_id, name='Synthetic activated hold', enabled=True, media_id='301', keywords=['price'],
            product_id=activated, private_reply='Earlier static copy must remain withheld.'),
        CatalogueProductMapping(business_id=business_id, product_id=activated, state='reviewed', revision=1,
            legacy_fingerprint='a' * 64, issues=[], legacy_variants=[])])
    await db.flush()
    db.add_all([CatalogueActivation(business_id=business_id, product_id=activated, reviewed_revision=1,
            legacy_fingerprint='a' * 64, actor_id=actor.user_id),
        CatalogueSKU(business_id=business_id, product_id=activated, options={'Size': 'M'}, price_minor=19999,
            currency='INR', stock_available=None, active=True)])
    return {'instagram_account': account, 'whatsapp_account': phone, 'waba': waba,
        'legacy_product': str(legacy), 'activated_product': str(activated)}


@app.post('/__test/comment-operator/{business_id}/drain')
async def drain(business_id: UUID, actor=Depends(require_v1_mutation), db=Depends(get_db)):
    await require_business_access(db, actor, business_id, 'automation.manage')
    ids = (await db.scalars(select(CommentAction.id).where(CommentAction.seller_id == business_id,
        CommentAction.status == 'pending').order_by(CommentAction.id))).all()
    await db.commit()
    for action_id in ids:
        await dispatch_one(db, action_id)
    return {'attempts': len(attempts)}


@app.get('/__test/comment-operator/{business_id}/stats')
async def stats(business_id: UUID, actor=Depends(require_v1_mutation), db=Depends(get_db)):
    await require_business_access(db, actor, business_id, 'inbox.read')
    account = await db.scalar(select(Seller.instagram_page_id).where(Seller.id == business_id))
    return {'commands': await db.scalar(select(func.count()).select_from(CommentOperatorCommand).where(CommentOperatorCommand.business_id == business_id)),
        'reviews': await db.scalar(select(func.count()).select_from(CommentOperatorReview).where(CommentOperatorReview.business_id == business_id)),
        'enquiries': await db.scalar(select(func.count()).select_from(WhatsAppEnquiryReview).where(WhatsAppEnquiryReview.business_id == business_id)),
        'enquiry_closures': await db.scalar(select(func.count()).select_from(WhatsAppEnquiryClosure).where(WhatsAppEnquiryClosure.business_id == business_id)),
        'rules': await db.scalar(select(func.count()).select_from(CommentRule).where(CommentRule.seller_id == business_id)),
        'wa_outbound': await db.scalar(select(func.count()).select_from(WhatsAppMessage).where(WhatsAppMessage.seller_id == business_id, WhatsAppMessage.direction == 'outbound')),
        'ig_attempts': [row['kind'] for row in attempts if row.get('account') == account],
        'wa_attempts': sum(row['channel'] == 'whatsapp' for row in attempts)}


@app.post('/__test/comment-operator/{business_id}/downgrade-self')
async def downgrade(business_id: UUID, actor=Depends(require_v1_mutation), db=Depends(get_db)):
    await require_business_access(db, actor, business_id, 'members.manage')
    await db.execute(update(Membership).where(Membership.business_id == business_id, Membership.user_id == actor.user_id).values(role='viewer'))
    return {'synthetic_current_role': 'viewer'}


if __name__ == '__main__':
    import uvicorn
    assert any(getattr(route, 'path', None) == '/api/v1/businesses/{business_id}/comment-automation' for route in app.routes), 'Shared router missing'
    uvicorn.run(app, host='127.0.0.1', port=8156, log_level='warning', ssl_certfile=sys.argv[1], ssl_keyfile=sys.argv[2])
