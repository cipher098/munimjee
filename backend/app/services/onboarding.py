"""Current local setup observations; configured accounts never prove delivery."""
from datetime import datetime,timedelta,timezone
from sqlalchemy import and_,func,select
from app.config import settings
from app.models.catalogue_v1 import CatalogueProductMapping,CatalogueSKU
from app.models.checkout_v1 import CatalogueActivation,CatalogueStorePolicy
from app.models.channel_operator import ChannelConnectionState
from app.models.commerce import Storefront
from app.models.identity import Business
from app.models.product import Product
from app.models.seller import Seller
from app.models.whatsapp import WhatsAppAccount
from app.services.identity import require_business_access


def profile_view(business):
    return {"business_id":business.id,"name":business.name,"profile":business.profile,
        "version":business.profile_version,"confirmed":business.profile_confirmed_at is not None}


async def local_channels(db,business_id):
    at=datetime.now(timezone.utc)
    seller=(await db.execute(select(Seller.instagram_page_id,Seller.instagram_token,
        Seller.instagram_token_expires_at).where(Seller.id==business_id))).one_or_none()
    wa=(await db.execute(select(WhatsAppAccount.phone_number_id,WhatsAppAccount.access_token,
        WhatsAppAccount.enabled,WhatsAppAccount.automation_enabled).where(WhatsAppAccount.seller_id==business_id))).one_or_none()
    controls=(await db.execute(select(ChannelConnectionState.channel,ChannelConnectionState.provider_account_id,
        ChannelConnectionState.check_status,ChannelConnectionState.checked_at,ChannelConnectionState.automation_enabled)
        .where(ChannelConnectionState.business_id==business_id))).all()
    result={}
    for channel in ('instagram','whatsapp'):
        control=next((c for c in controls if c.channel==channel),None)
        account=seller.instagram_page_id if channel=='instagram' and seller else wa.phone_number_id if wa else None
        configured=bool(seller and seller.instagram_page_id and seller.instagram_token and
            seller.instagram_token_expires_at and seller.instagram_token_expires_at>at) if channel=='instagram' else bool(wa and wa.access_token)
        verified=bool(control and configured and account==control.provider_account_id and
            control.check_status=='verified' and control.checked_at and at-timedelta(hours=24)<=control.checked_at<=at+timedelta(minutes=5))
        webhook=bool(settings.META_WEBHOOK_SECRET) if channel=='instagram' else bool(settings.WHATSAPP_APP_SECRET and settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN)
        enabled=bool(control and control.automation_enabled) if channel=='instagram' else bool(wa and wa.enabled and wa.automation_enabled)
        result[channel]={'configured':configured,'local_account_access_verified':verified,
            'webhook_configured':webhook,'automation_enabled':enabled,
            'ready':bool(verified and webhook and enabled)}
    return result


async def onboarding_view(db,actor,business_id,*,available_actions=frozenset()):
    await require_business_access(db,actor,business_id,'readiness.read')
    reviewed=await db.scalar(select(func.count()).select_from(CatalogueProductMapping).where(
        CatalogueProductMapping.business_id==business_id,CatalogueProductMapping.state=='reviewed'))
    active=(await db.execute(select(func.count(func.distinct(Product.id)),func.count(CatalogueSKU.id)).select_from(Product)
        .join(CatalogueProductMapping,and_(CatalogueProductMapping.product_id==Product.id,
            CatalogueProductMapping.business_id==business_id,CatalogueProductMapping.state=='reviewed'))
        .join(CatalogueActivation,and_(CatalogueActivation.product_id==Product.id,CatalogueActivation.business_id==business_id))
        .join(CatalogueSKU,and_(CatalogueSKU.product_id==Product.id,CatalogueSKU.business_id==business_id,CatalogueSKU.active.is_(True)))
        .where(Product.seller_id==business_id,Product.active.is_(True)))).one()
    channels=await local_channels(db,business_id)
    store=(await db.execute(select(Storefront.slug,Storefront.published,Storefront.currency,Storefront.cod_enabled)
        .where(Storefront.seller_id==business_id))).one_or_none()
    policy=await db.scalar(select(CatalogueStorePolicy.checkout_enabled).where(CatalogueStorePolicy.business_id==business_id))
    payment_ready=bool(store and store.cod_enabled)
    if store and store.published and not payment_ready:
        from app.services.checkout_sessions import public_payment_options
        payment_ready=(await public_payment_options(store.slug,db))['razorpay_enabled']
    # Fresh scalar profile avoids a retained ORM snapshot across the above awaits.
    row=(await db.execute(select(Business.id,Business.name,Business.profile,Business.profile_version,
        Business.profile_confirmed_at).where(Business.id==business_id))).one()
    profile={'business_id':row.id,'name':row.name,'profile':row.profile,'version':row.profile_version,
        'confirmed':row.profile_confirmed_at is not None}
    catalogue_ready=active[0]>0
    channels_ready=all(c['ready'] for c in channels.values())
    storefront_ready=bool(store and store.published and store.currency=='INR' and policy and catalogue_ready and
        payment_ready and settings.V1_STOREFRONT_ENABLED)
    catalogue_url=f'/v1/businesses/{business_id}/catalogue';channel_url=f'/v1/businesses/{business_id}/channels'
    steps=[
        {'id':'identity','label':'Account and access','status':'ready','reason':'Your active membership is confirmed.','action_url':None},
        {'id':'business_profile','label':'Business details','status':'ready' if profile['confirmed'] else 'action_required',
         'reason':'Business details saved.' if profile['confirmed'] else 'Confirm the boutique details used by your team.','action_url':'#profile'},
        {'id':'catalogue','label':'Reviewed catalogue','status':'ready' if catalogue_ready else 'action_required',
         'reason':f'{active[0]} active reviewed products with {active[1]} active SKUs. Current stock remains a checkout-time observation.' if catalogue_ready else
             f'{reviewed} reviewed snapshots. Explicit product activation and reviewed SKU allocation are still required.','action_url':catalogue_url},
        {'id':'channels','label':'Instagram and WhatsApp setup','status':'ready' if channels_ready else 'action_required',
         'reason':'Both accounts passed recent local access checks and are enabled. Provider approvals and message delivery are not inferred.' if channels_ready else
             'Connect the intended accounts, check current access and webhook setup, then explicitly enable eligible automation. Local checks do not prove delivery.','action_url':channel_url},
        {'id':'storefront','label':'Storefront and checkout','status':'ready' if storefront_ready else 'action_required',
         'reason':'The public runtime, published storefront, activated catalogue, checkout policy and an available payment method are configured.' if storefront_ready else
             'Publish the storefront, activate reviewed products and enable checkout with an available payment method. The public storefront runtime must also be enabled.','action_url':catalogue_url},
        {'id':'channel_test','label':'Authorized messaging acceptance','status':'action_required',
         'reason':'A consented real-recipient message test and recorded result are still required. Saved credentials and account-access checks do not prove delivery.',
         'action_url':None,'action_unavailable_reason':'An authorized message-test workflow is not available in this preview.'},
    ]
    for step in steps:
        if step['action_url'] and step['action_url'].startswith('/') and step['action_url'] not in available_actions:
            step['action_url']=None;step['action_unavailable_reason']='This workspace is not available in the current preview.'
    # The route's final current-session/capability guard owns response authority.
    await require_business_access(db,actor,business_id,'readiness.read')
    return {'business_id':business_id,'onboarding_complete':False,
        'local_setup_complete':all(s['status']=='ready' for s in steps if s['id']!='channel_test'),
        'completed_steps':sum(s['status']=='ready' for s in steps),'total_steps':len(steps),
        'steps':steps,'profile':profile,'local_channels':channels,
        'external_readiness':{'provider_approval':'not_evaluated','message_test':'not_recorded'}}
