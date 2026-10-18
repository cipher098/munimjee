"""Actual app.main plus explicit test-only synthetic inbox/connection fixtures."""
from tests.safety import install_test_safety
install_test_safety()
from uuid import UUID, uuid4
from fastapi import Depends, Request
from sqlalchemy import select, update, func
from app.config import settings
settings.V1_AUTH_ENABLED = True
settings.V1_ENFORCE_LEGACY_ACCESS = True
settings.V1_CUSTOMER_LINKS_ENABLED = True
settings.PUBLIC_BASE_URL = 'http://127.0.0.1:8156'
settings.META_WEBHOOK_SECRET = 'synthetic-browser-link-signature'
settings.WHATSAPP_APP_SECRET = 'synthetic-browser-link-signature'
from app.main import app
from app.api.v1.session import require_v1_mutation
from app.database import get_db
from app.models.seller import Seller
from app.models.conversation import Conversation
from app.models.whatsapp import WhatsAppAccount, WhatsAppContact
from app.models.identity import Membership
from app.models.identity_auth import UserSession
from app.models.customer_links import Customer, CustomerLinkChallenge, CustomerLinkProof, CustomerLinkAudit
from app.services.identity import require_business_access


@app.post('/__test/customer-links/{business_id}/seed')
async def seed(business_id: UUID, request: Request, actor=Depends(require_v1_mutation), db=Depends(get_db)):
    await require_business_access(db, actor, business_id, 'channels.connect')
    account = str(uuid4().int)[:15]
    wa = str(uuid4().int)[:15]
    waba = str(uuid4().int)[:15]
    conversation, contact = uuid4(), uuid4()
    await db.execute(update(Seller).where(Seller.id == business_id).values(instagram_id=account,
        instagram_page_id=account, instagram_token='synthetic-not-a-provider-credential'))
    db.add_all([Conversation(id=conversation,seller_id=business_id,customer_instagram_id='12345678901',customer_name='Synthetic Customer',messages=[{'role':'customer','content':'Earlier synthetic enquiry'}]),
        WhatsAppAccount(seller_id=business_id,phone_number_id=wa,waba_id=waba,access_token='synthetic-encrypted-fixture',enabled=False),
        WhatsAppContact(id=contact,seller_id=business_id,phone='919876543210',name='Synthetic Customer')])
    return {'conversation_id':str(conversation),'contact_id':str(contact),'instagram_account':account,'whatsapp_account':wa,'waba':waba}


@app.get('/__test/customer-links/{business_id}/counts')
async def counts(business_id: UUID,request: Request,db=Depends(get_db)):
    from app.api.v1.identity import current_actor
    actor=await current_actor(request,db)
    await require_business_access(db,actor,business_id,'inbox.read')
    return {name:await db.scalar(select(func.count()).select_from(model).where(model.business_id==business_id))
        for name,model in [('customers',Customer),('challenges',CustomerLinkChallenge),('proofs',CustomerLinkProof),('audits',CustomerLinkAudit)]}


@app.post('/__test/customer-links/{business_id}/downgrade')
async def downgrade(business_id:UUID,actor=Depends(require_v1_mutation),db=Depends(get_db)):
    await require_business_access(db,actor,business_id,'members.manage')
    await db.execute(update(Membership).where(Membership.business_id==business_id,Membership.user_id==actor.user_id).values(role='staff'))
    return {'synthetic_fixture':'role_downgraded'}


@app.post('/__test/customer-links/{business_id}/expire')
async def expire(business_id:UUID,actor=Depends(require_v1_mutation),db=Depends(get_db)):
    await require_business_access(db,actor,business_id,'inbox.read')
    await db.execute(update(UserSession).where(UserSession.user_id==actor.user_id).values(revoked_at=func.clock_timestamp()))
    return {'synthetic_fixture':'native_session_revoked'}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8156,log_level='warning')
