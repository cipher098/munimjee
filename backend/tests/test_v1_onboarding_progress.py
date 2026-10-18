"""Actual native setup observations and private-read response authority."""
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from sqlalchemy import select,update
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.models.channel_operator import ChannelConnectionState
from app.models.identity import Membership
from app.models.identity_auth import UserSession
from app.models.seller import Seller
from app.models.whatsapp import WhatsAppAccount
from app.services.auth_sessions import now_utc
from tests.test_v1_native_completion_import_http import native_import


def step(data,key):return next(s for s in data['steps'] if s['id']==key)


@pytest.mark.asyncio
async def test_actual_profile_activation_publication_progress_keeps_test_unproven(native_import,monkeypatch):
    j=native_import;path=f'/api/v1/businesses/{j.bid}/onboarding';cat=f'/api/v1/businesses/{j.bid}/catalogue'
    initial=(await j.client.get(path)).json();assert initial['completed_steps']==1 and initial['total_steps']==6
    assert initial['onboarding_complete'] is False and step(initial,'channel_test')['action_url'] is None
    saved=await j.client.put(f'/api/v1/businesses/{j.bid}/profile',headers=j.csrf,
        json={'expected_version':0,'name':'Synthetic ready boutique','business_type':'boutique','country':'IN'})
    assert saved.status_code==200,saved.text
    draft=await j.client.post(cat+'/products',headers=j.csrf,json={'idempotency_key':str(uuid4()),'seller_reviewed':True,
        'name':'Reviewed dress','skus':[{'options':{},'price_minor':1200,'currency':'INR','stock_available':0,'active':True}]})
    assert draft.status_code==201,draft.text;d=draft.json();pid=d['product']['product_id']
    assert step((await j.client.get(path)).json(),'catalogue')['status']=='action_required'
    response=await j.client.post(cat+f'/products/{pid}/activate',headers=j.csrf,json={'seller_reviewed':True,
        'expected_mapping_revision':d['mapping_revision'],'expected_legacy_fingerprint':d['legacy_fingerprint']})
    assert response.status_code==200,response.text
    assert (await j.client.put(cat+'/checkout-policy',headers=j.csrf,json={'checkout_enabled':True})).status_code==200
    async with j.sessions() as db:
        from app.models.commerce import Storefront
        slug=(await db.get(Storefront,j.bid)).slug
    assert (await j.client.put(cat+'/storefront',headers=j.csrf,json={'name':'Synthetic ready boutique','slug':slug,'published':True,'cod_enabled':True,'shipping_fee':0})).status_code==200
    current=(await j.client.get(path)).json();assert current['completed_steps']==4
    assert step(current,'catalogue')['status']==step(current,'storefront')['status']=='ready'
    assert not current['local_setup_complete'] and not current['onboarding_complete']
    # These are synthetic local-check records, deliberately not delivery evidence.
    at=datetime.now(timezone.utc)
    monkeypatch.setattr(settings,'META_WEBHOOK_SECRET','synthetic-signature-key')
    monkeypatch.setattr(settings,'WHATSAPP_APP_SECRET','synthetic-whatsapp-key')
    monkeypatch.setattr(settings,'WHATSAPP_WEBHOOK_VERIFY_TOKEN','synthetic-verify')
    async with j.sessions.begin() as db:
        seller=await db.get(Seller,j.bid);seller.instagram_page_id='190000000000001';seller.instagram_token='synthetic-token';seller.instagram_token_expires_at=at+timedelta(hours=2)
        db.add(WhatsAppAccount(seller_id=j.bid,phone_number_id='190000000000002',waba_id='190000000000003',access_token='synthetic-ciphertext',enabled=True,automation_enabled=True))
        for channel,account in [('instagram','190000000000001'),('whatsapp','190000000000002')]:
            db.add(ChannelConnectionState(business_id=j.bid,channel=channel,provider_account_id=account,version=1,
                check_status='verified',checked_at=at,automation_enabled=True))
    current=(await j.client.get(path)).json();assert current['local_setup_complete'] and current['completed_steps']==5
    assert current['onboarding_complete'] is False and current['external_readiness']['message_test']=='not_recorded'
    assert step(current,'channel_test')['status']=='action_required'
    async with j.sessions.begin() as db:(await db.get(WhatsAppAccount,j.bid)).automation_enabled=False
    paused=(await j.client.get(path)).json()
    assert not paused['local_setup_complete'] and step(paused,'channels')['status']=='action_required'
    assert paused['local_channels']['whatsapp']['automation_enabled'] is False
    async with j.sessions.begin() as db:(await db.get(Seller,j.bid)).instagram_token_expires_at=at-timedelta(seconds=1)
    assert step((await j.client.get(path)).json(),'channels')['status']=='action_required'
    monkeypatch.setattr(settings,'V1_STOREFRONT_ENABLED',False)
    assert step((await j.client.get(path)).json(),'storefront')['status']=='action_required'


@pytest.mark.asyncio
async def test_onboarding_session_revoke_after_final_profile_query_discards_read(native_import,monkeypatch):
    j=native_import;original=AsyncSession.execute;changed=False
    async def execute(db,statement,*args,**kwargs):
        nonlocal changed
        result=await original(db,statement,*args,**kwargs)
        if not changed and 'businesses.profile_version' in str(statement) and 'JOIN' not in str(statement):
            changed=True
            async with j.sessions.begin() as other:await other.execute(update(UserSession).where(UserSession.user_id==j.uid).values(revoked_at=now_utc()))
        return result
    monkeypatch.setattr(AsyncSession,'execute',execute)
    response=await j.client.get(f'/api/v1/businesses/{j.bid}/onboarding')
    assert changed and response.status_code==401,response.text
    assert 'Synthetic' not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize('resource',['invitations','members'])
async def test_team_role_revoke_after_private_query_discards_read(native_import,monkeypatch,resource):
    j=native_import;original=AsyncSession.execute;changed=False
    async def execute(db,statement,*args,**kwargs):
        nonlocal changed
        result=await original(db,statement,*args,**kwargs)
        target='FROM business_invitations' if resource=='invitations' else 'FROM memberships'
        if not changed and target in str(statement) and 'JOIN' not in str(statement):
            changed=True
            async with j.sessions.begin() as other:await other.execute(update(Membership).where(Membership.business_id==j.bid,Membership.user_id==j.uid).values(role='viewer'))
        return result
    monkeypatch.setattr(AsyncSession,'execute',execute)
    response=await j.client.get(f'/api/v1/businesses/{j.bid}/{resource}')
    assert changed and response.status_code==403,response.text
