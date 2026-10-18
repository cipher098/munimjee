"""Isolated rendered-report fixture: real main/native/PG; synthetic source facts.

No provider transport or provider acceptance is proved here. The canonical
receipt-shaped state is explicitly a synthetic outcome fixture.
"""
from tests.safety import install_test_safety
install_test_safety()
import sys
from uuid import UUID,uuid4
from fastapi import Depends,HTTPException,Request
from app.config import settings
settings.V1_AUTH_ENABLED=True
settings.V1_ENFORCE_LEGACY_ACCESS=True
settings.V1_ACTIVITY_ENABLED=True
settings.V1_ACTIVITY_RETENTION_READY=True
settings.APP_ENV='production'  # Synthetic classification only.
settings.PUBLIC_BASE_URL='http://127.0.0.1:8170'
from app.main import app
from app.database import get_db
from app.api.v1.session import require_v1_mutation
from app.models.whatsapp import WhatsAppAccount,WhatsAppContact,WhatsAppMessage
from app.services import activity_v1,activity_producers,whatsapp,instagram_ingress
from app.services import whatsapp_provider,razorpay_payments
from app.integrations.instagram import InstagramClient
nonce=sys.argv[1]
calls=[]
async def forbidden(*a,**kw):
    calls.append(True)
    raise AssertionError('No provider transport is allowed in activity render fixture')
whatsapp_provider.graph=forbidden
whatsapp_provider.send=forbidden
InstagramClient.send_message=forbidden
razorpay_payments.gateway_request=forbidden


@app.get('/__channel_activity/identify')
async def identify():
    path='/api/v1/businesses/{business_id}/analytics/activity'
    mounts=[r for r in app.routes if getattr(r,'path',None)==path]
    return {'nonce':nonce,'provider_calls':len(calls),'actual_mounts':len(mounts),
        'actual_module':mounts[0].endpoint.__module__ if len(mounts)==1 else None}


@app.post('/__channel_activity/{business_id}/synthetic-sources')
async def sources(business_id:UUID,request:Request,db=Depends(get_db)):
    if request.headers.get('x-fixture-nonce')!=nonce:raise HTTPException(404)
    actor=await require_v1_mutation(request,db)
    await activity_v1.owner(db,actor,business_id)
    from app.models.seller import Seller
    seller=await db.get(Seller,business_id);seller.instagram_page_id='synthetic-account'
    account=WhatsAppAccount(seller_id=business_id,phone_number_id='synthetic-phone',
        waba_id='synthetic-waba',access_token='unused-synthetic-ciphertext',enabled=True)
    contact=WhatsAppContact(seller_id=business_id,phone='919876543210',last_inbound_at=whatsapp.now())
    db.add_all([account,contact]);await db.flush()
    # Real new-row producer plus exact replay: one inbound observation.
    event={'sender':{'id':'synthetic-customer'},'recipient':{'id':'synthetic-account'},
        'message':{'mid':'synthetic-mid','text':'private-fixture-body'}}
    await instagram_ingress.persist_message(db,event)
    await instagram_ingress.persist_message(db,event)
    for state in ('queued','unknown','receipt'):
        row=await whatsapp.queue_message(db,account,contact,key='synthetic-auto:'+state,text='private-fixture-body',
            activity_producer=activity_producers.AutomatedWhatsAppProducer.INBOUND_REPLY)
        if state!='queued':row.status='unknown'
        if state=='receipt':row.provider_message_id='synthetic-receipt-NOT-provider-proof'
    await whatsapp.queue_message(db,account,contact,key='auto:misleading-manual-prefix',text='private-fixture-body')
    test=WhatsAppMessage(seller_id=business_id,contact_id=contact.id,phone_number_id=account.phone_number_id,
        idempotency_key='synthetic-known-test',direction='outbound',text='private-fixture-body',status='queued')
    db.add(test);await db.flush()
    await activity_v1.record_source(db,business_id,'wa_outbound',test.id,origin='automated',is_new=True,test_evidence=True)
    return {'synthetic_source_facts':True,'provider_transport_proof':False}


if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8170,log_level='warning')
