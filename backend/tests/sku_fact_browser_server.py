"""Actual app.main; synthetic account bindings/provider only, exclusive P01 lane."""
from tests.safety import install_test_safety
install_test_safety()
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from fastapi import Depends, HTTPException
from sqlalchemy import func, select, update
from app.config import settings
settings.V1_AUTH_ENABLED=True
settings.V1_ENFORCE_LEGACY_ACCESS=True
settings.V1_SKU_FACT_REPLIES_ENABLED=True
settings.META_WEBHOOK_SECRET=settings.WHATSAPP_APP_SECRET='synthetic-sku-signature'
settings.PUBLIC_BASE_URL='http://127.0.0.1:8156'
from app.main import app
from app.api.v1.session import require_v1_mutation
from app.database import get_db
from app.models.seller import Seller
from app.models.conversation import Conversation
from app.models.conversation_product import ConversationProduct
from app.models.commerce import CommerceOrder
from app.models.checkout_v1 import SKUReservation
from app.models.instagram_ingress import InstagramIngress
from app.models.product import Product
from app.models.whatsapp import WhatsAppAccount, WhatsAppContact, WhatsAppMessage
from app.services.identity import require_business_access
from app.integrations.instagram import InstagramClient
from app.services import whatsapp_provider
from app.workers.instagram_ingress import process_instagram_ingress, _process_thread
from app.workers.whatsapp import deliver_one

fixtures={}
sends=[]
process_instagram_ingress.apply_async=lambda **kwargs:None


async def instagram_send(client,recipient,text):
    business=next(bid for bid,value in fixtures.items() if value['instagram_account']==client.fb_page_id)
    sends.append({'business_id':str(business),'channel':'instagram','text':text})
    return {'message_id':'synthetic-'+uuid4().hex}


async def whatsapp_send(account,contact,message):
    sends.append({'business_id':str(account.seller_id),'channel':'whatsapp','text':message.text})
    return 'synthetic-'+uuid4().hex


InstagramClient.send_message=instagram_send
whatsapp_provider.send=whatsapp_send


@app.post('/__test/sku-facts/{business_id}/{product_id}/bind')
async def bind(business_id:UUID,product_id:UUID,actor=Depends(require_v1_mutation),db=Depends(get_db)):
    await require_business_access(db,actor,business_id,'automation.manage')
    product=await db.scalar(select(Product).where(Product.id==product_id,Product.seller_id==business_id))
    if product is None:raise HTTPException(404)
    ig,wa,waba=(str(uuid4().int)[:15] for _ in range(3))
    customer='12345678901';contact=uuid4()
    await db.execute(update(Seller).where(Seller.id==business_id).values(instagram_id=ig,
        instagram_page_id=ig,fb_page_id=ig,instagram_token='synthetic-never-provider-token'))
    product.reel_urls=['https://www.instagram.com/reel/Synthetic_sku/']
    db.add_all([Conversation(seller_id=business_id,product_id=product_id,customer_instagram_id=customer,
            customer_name='Synthetic customer',messages=[]),
        WhatsAppAccount(seller_id=business_id,phone_number_id=wa,waba_id=waba,access_token='synthetic-not-decrypted',
            enabled=True,automation_enabled=True,reel_replies_enabled=True),
        WhatsAppContact(id=contact,seller_id=business_id,phone='919876543210',last_inbound_at=datetime.now(timezone.utc))])
    fixtures[business_id]={'instagram_account':ig,'whatsapp_account':wa,'waba':waba,'customer':customer}
    return fixtures[business_id]


@app.post('/__test/sku-facts/{business_id}/{product_id}/second-reel')
async def second_reel(business_id:UUID,product_id:UUID,actor=Depends(require_v1_mutation),db=Depends(get_db)):
    await require_business_access(db,actor,business_id,'automation.manage')
    product=await db.scalar(select(Product).where(Product.id==product_id,Product.seller_id==business_id))
    if product is None:raise HTTPException(404)
    product.reel_urls=['https://www.instagram.com/reel/Second_sku/']
    return {'synthetic_mapping':'Second_sku'}


@app.post('/__test/sku-facts/{business_id}/drain')
async def drain(business_id:UUID,actor=Depends(require_v1_mutation),db=Depends(get_db)):
    await require_business_access(db,actor,business_id,'automation.manage')
    fixture=fixtures[business_id]
    await db.execute(update(InstagramIngress).where(InstagramIngress.seller_id==business_id,
        InstagramIngress.status=='pending').values(available_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
    mids=(await db.scalars(select(WhatsAppMessage.id).where(WhatsAppMessage.seller_id==business_id,
        WhatsAppMessage.direction=='outbound',WhatsAppMessage.status=='queued'))).all()
    await db.commit()
    await _process_thread(business_id,fixture['instagram_account'],fixture['customer'])
    for mid in mids:await deliver_one(mid)
    receipts=(await db.execute(select(InstagramIngress.status,InstagramIngress.error_code).where(
        InstagramIngress.seller_id==business_id).order_by(InstagramIngress.created_at))).all()
    return {'sends':[row for row in sends if row['business_id']==str(business_id)],
        'receipts':[{'status':status,'error_code':error} for status,error in receipts],
        'mutations':{name:await db.scalar(select(func.count()).select_from(model)) for name,model in
            [('orders',CommerceOrder),('reservations',SKUReservation),('cycles',ConversationProduct)]}}


if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8156,log_level='warning')
