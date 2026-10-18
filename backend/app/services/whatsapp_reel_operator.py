"""One reviewed inbound → mapping and optional canonical outbox intent.

No provider, internal commit, historical-context rewrite or second sender lives here.
Integrator installs revalidate_resume at the final existing dispatch boundary.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from uuid import UUID, uuid4

from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import select, text, func, tuple_, Text
from sqlalchemy.exc import DBAPIError

from app.config import settings
from app.models.channel_operator import ChannelConnectionState
from app.models.product import Product
from app.models.whatsapp import WhatsAppAccount, WhatsAppContact, WhatsAppMessage
from app.models.whatsapp_reel_operator import WhatsAppReelCommand as Command, WhatsAppReelAuthorization as Authorization
from app.services import sku_fact_replies as facts, whatsapp as wa
from app.services.identity import require_business_access
from app.services.whatsapp_context import instagram_references

EXPLICIT = frozenset({'message_link','referral_link','quoted_message'})


@dataclass(frozen=True)
class ReviewerBinding:
    user_id: UUID
    session_id: UUID
    auth_version: int


def canonical(value):
    if isinstance(value, (UUID, datetime)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical(item) for item in value]
    return value


def fingerprint(value):
    return hashlib.sha256(json.dumps(canonical(value),sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()


def request_hash(business_id, inbound_id, command):
    return fingerprint({'business_id':str(business_id),'inbound_id':str(inbound_id),'body':command.model_dump(mode='json')})


def source_digest(model=WhatsAppMessage):
    return func.wa_reel_source_fingerprint(model.payload,model.text,model.kind,model.created_at,
        model.provider_message_id,model.contact_id,model.phone_number_id)


def mapping_digest(model=Product):
    return func.encode(func.sha256(func.convert_to(func.coalesce(model.reel_urls, text("'[]'::jsonb")).cast(Text),'UTF8')),'hex')


async def access(db, actor, business_id, *, write=False):
    if not settings.V1_AUTH_ENABLED:
        raise HTTPException(404,'Native sign-in is unavailable')
    if actor.auth_method!='v1_user':
        raise HTTPException(401,'Native sign-in required')
    return await require_business_access(db,actor,business_id,'automation.manage' if write else 'inbox.read')


async def source_row(db,business_id,inbound_id,*,lock=False):
    query=select(WhatsAppMessage,source_digest().label('source_fingerprint')).where(
        WhatsAppMessage.id==inbound_id,WhatsAppMessage.seller_id==business_id,WhatsAppMessage.direction=='inbound')
    if lock:
        query=query.with_for_update(of=WhatsAppMessage)
    row=(await db.execute(query.execution_options(populate_existing=True,autoflush=False))).one_or_none()
    if row is None:
        raise HTTPException(404,'Enquiry not found')
    return row[0],row[1]


async def original_reference(db,business_id,message):
    context=(message.payload or {}).get('reel_context',{})
    classification=context.get('source','unknown')
    refs=context.get('references',[])
    result={'classification':classification if classification in EXPLICIT|{'recent_message'} else 'unknown',
            'shortcode':None,'url':None}
    if not isinstance(refs,list) or len(refs)!=1 or not isinstance(refs[0],dict):
        return result,None,None,'ambiguous_source'
    parsed=instagram_references(refs[0].get('url',''))
    if len(parsed)!=1 or parsed[0].get('shortcode')!=refs[0].get('shortcode'):
        return result,None,None,'source_changed'
    ref=parsed[0]; result.update(ref)
    quoted_id=quoted_fp=None
    if classification=='message_link':
        resolved=instagram_references(message.text)
    elif classification=='referral_link':
        resolved=instagram_references((message.payload or {}).get('referral',{}).get('source_url',''))
    elif classification=='quoted_message':
        quoted=(await db.execute(select(WhatsAppMessage,source_digest()).where(
            WhatsAppMessage.seller_id==business_id,WhatsAppMessage.contact_id==message.contact_id,
            WhatsAppMessage.phone_number_id==message.phone_number_id,
            WhatsAppMessage.provider_message_id==(message.payload or {}).get('reply_to_message_id','')).execution_options(autoflush=False))).one_or_none()
        if quoted is None:
            return result,None,None,'quoted_source_unavailable'
        original,quoted_fp=quoted; quoted_id=original.id
        old=(original.payload or {}).get('reel_context',{}).get('references',[])
        resolved=instagram_references(' '.join(r.get('url','') for r in old if isinstance(r,dict))) or instagram_references(original.text)
    elif classification=='recent_message':
        return result,None,None,'inferred_context'
    else:
        return result,None,None,'unsupported_source'
    if resolved!=[ref]:
        return result,None,None,'source_changed'
    return result,quoted_id,quoted_fp,None


async def review_state(db,business_id,inbound_id,*,locked=None):
    message,source_fp=locked or await source_row(db,business_id,inbound_id)
    account=await db.scalar(select(WhatsAppAccount).where(WhatsAppAccount.seller_id==business_id).execution_options(populate_existing=True,autoflush=False))
    contact=await db.scalar(select(WhatsAppContact).where(WhatsAppContact.id==message.contact_id,WhatsAppContact.seller_id==business_id).execution_options(populate_existing=True,autoflush=False))
    if contact is None:
        raise HTTPException(404,'Enquiry not found')
    control=(await db.execute(select(ChannelConnectionState.version,ChannelConnectionState.automation_enabled).where(
        ChannelConnectionState.business_id==business_id,ChannelConnectionState.channel=='whatsapp'))).one_or_none()
    version=control.version if control else None
    control_enabled=control.automation_enabled if control else False
    source,quoted_id,quoted_fp,reason=await original_reference(db,business_id,message)
    matches=await facts.exact_reel_products(db,business_id,reel_url=source['url']) if source['url'] else ()
    ids=tuple(matches or ())
    candidates=[dict(row) for row in (await db.execute(select(Product.id,Product.name).where(
        Product.seller_id==business_id,Product.active.is_(True)).order_by(Product.id).limit(50).execution_options(autoflush=False))).mappings()]
    names=[dict(row) for row in (await db.execute(select(Product.id,Product.name).where(
        Product.seller_id==business_id,Product.active.is_(True),Product.id.in_(ids)).order_by(Product.id).execution_options(autoflush=False))).mappings()] if ids else []
    newer=await db.scalar(select(WhatsAppMessage.id).where(WhatsAppMessage.seller_id==business_id,
        WhatsAppMessage.contact_id==contact.id,WhatsAppMessage.direction=='inbound',
        WhatsAppMessage.created_at>=message.created_at,WhatsAppMessage.id!=message.id).limit(1))
    prior=await db.scalar(select(WhatsAppMessage.id).where(WhatsAppMessage.seller_id==business_id,
        WhatsAppMessage.contact_id==contact.id,WhatsAppMessage.direction=='outbound',
        WhatsAppMessage.created_at>=message.created_at).limit(1))
    at=wa.now()
    if reason is None:
        reason=('account_unavailable' if not account or not account.access_token else
            'account_changed' if account.phone_number_id!=message.phone_number_id else
            'automation_paused' if not (account.enabled and account.automation_enabled and account.reel_replies_enabled and control_enabled) else
            'opted_out' if contact.opted_out else
            'reply_window_closed' if not wa.window_open(contact) or not at-timedelta(hours=24)<message.created_at<=at else
            'newer_customer_message' if newer else 'reply_already_attempted' if prior else
            'consent_command' if message.text.strip().casefold() in {'stop','unsubscribe','start'} else
            'source_unverified' if not message.provider_message_id else
            'ambiguous_mapping' if matches is None or len(ids)>1 else
            'catalogue_authority_unavailable' if not facts.enabled() else None)
    credential=hashlib.sha256(account.access_token.encode()).hexdigest() if account else hashlib.sha256(b'').hexdigest()
    state=dict(source_fingerprint=source_fp,quoted_id=quoted_id,quoted_fingerprint=quoted_fp,source=source,
        connection_version=version if version is not None else 0,control_present=version is not None,credential=credential,
        account_phone=account.phone_number_id if account else None,waba=account.waba_id if account else None,
        enabled=account.enabled if account else False,automation=account.automation_enabled if account else False,
        reels=account.reel_replies_enabled if account else False,control_enabled=control_enabled,contact_last=contact.last_inbound_at,
        opted_out=contact.opted_out,newer=newer,prior=prior,matches=ids,candidates=candidates,
        recipient_fingerprint=hashlib.sha256(contact.phone.encode()).hexdigest())
    return message,account,contact,state,reason,names,candidates


def review_view(business_id,values,can_manage):
    message,account,contact,state,reason,names,candidates=values
    source=state['source']; can_link=bool(source['shortcode'] and source['classification']!='unknown')
    return canonical(dict(business_id=business_id,inbound_id=message.id,message=message.text,received_at=message.created_at,
        customer_name=contact.name,customer_ref=contact.phone[-4:],account_hint='…'+account.phone_number_id[-6:] if account else 'Not connected',
        source=source,connection_version=state['connection_version'],fingerprint=fingerprint(state),matches=names,products=candidates,
        eligibility=dict(can_link=can_link,can_resume=can_link and reason is None,reason=reason),can_manage=can_manage))


async def read_enquiry(db,actor,business_id,inbound_id):
    await access(db,actor,business_id)
    values=await review_state(db,business_id,inbound_id)
    current=await access(db,actor,business_id)
    return review_view(business_id,values,'automation.manage' in current.capabilities)


async def list_enquiries(db,actor,business_id,*,cursor=None,limit=20):
    await access(db,actor,business_id)
    if not 1<=limit<=50:
        raise HTTPException(422,'Use a bounded enquiry page')
    query=select(WhatsAppMessage.id,WhatsAppMessage.created_at).where(WhatsAppMessage.seller_id==business_id,
        WhatsAppMessage.direction=='inbound',WhatsAppMessage.payload.has_key('reel_context'))
    if cursor:
        try:
            value=jwt.decode(cursor,settings.SECRET_KEY,algorithms=['HS256'])
            if value['purpose']!='native-reel-page.v1' or value['business']!=str(business_id):
                raise ValueError()
            query=query.where(tuple_(WhatsAppMessage.created_at,WhatsAppMessage.id)<tuple_(datetime.fromisoformat(value['at']),UUID(value['id'])))
        except (JWTError,ValueError,KeyError,TypeError):
            raise HTTPException(422,'Refresh this enquiry page') from None
    rows=(await db.execute(query.order_by(WhatsAppMessage.created_at.desc(),WhatsAppMessage.id.desc()).limit(limit+1))).all()
    items=[await read_enquiry(db,actor,business_id,row.id) for row in rows[:limit]]
    more=None
    if len(rows)>limit:
        last=rows[limit-1]
        more=jwt.encode({'purpose':'native-reel-page.v1','business':str(business_id),'at':last.created_at.isoformat(),
            'id':str(last.id),'exp':datetime.now(timezone.utc)+timedelta(minutes=30)},settings.SECRET_KEY,algorithm='HS256')
    current=await access(db,actor,business_id)
    return {'items':items,'next_cursor':more,'can_manage':'automation.manage' in current.capabilities}


def receipt_view(row,*,replayed=False):
    return canonical(dict(business_id=row.business_id,inbound_id=row.inbound_message_id,command_id=row.id,
        idempotency_key=row.idempotency_key,action=row.action,product_id=row.product_id,request_hash=row.request_hash,
        result=row.result,replayed=replayed))


async def link_enquiry(db,actor,business_id,inbound_id,command,*,request_authority):
    await access(db,actor,business_id,write=True)
    binding=await request_authority()
    if not isinstance(binding,ReviewerBinding) or binding.user_id!=actor.user_id:
        raise HTTPException(401,'Current native session required')
    async def guard():
        await access(db,actor,business_id,write=True)
        if await request_authority()!=binding:
            raise HTTPException(401,'The authorizing native session changed')
    digest=request_hash(business_id,inbound_id,command)
    await db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:scope))'),{'scope':'native-reel-command:'+str(business_id)+':'+str(command.idempotency_key)})
    await guard()
    saved=await db.scalar(select(Command).where(Command.business_id==business_id,Command.idempotency_key==command.idempotency_key).execution_options(populate_existing=True,autoflush=False))
    if saved:
        if (saved.actor_user_id,saved.actor_session_id,saved.actor_auth_version,saved.request_hash)!=(binding.user_id,binding.session_id,binding.auth_version,digest):
            raise HTTPException(409,'This command key belongs to different saved facts or reviewer')
        await guard()
        return receipt_view(saved,replayed=True)
    def reject(reason):
        raise HTTPException(409,dict(code='reel_operator_pre_mutation_rejection',business_id=str(business_id),
            inbound_id=str(inbound_id),idempotency_key=str(command.idempotency_key),request_hash=digest,accepted=False,reason=reason))
    preliminary,_=await source_row(db,business_id,inbound_id)
    account=await db.scalar(select(WhatsAppAccount).where(WhatsAppAccount.seller_id==business_id).with_for_update().execution_options(populate_existing=True))
    if account is None:
        reject('account_unavailable')
    contact=await wa.contact_for(db,business_id,preliminary.contact_id,lock=True)
    locked=await source_row(db,business_id,inbound_id,lock=True)
    await guard()
    if locked[0].contact_id!=contact.id:
        reject('source_changed')
    values=await review_state(db,business_id,inbound_id,locked=locked)
    message,account,contact,state,reason,_,_=values
    if not state['control_present'] or not message.provider_message_id:
        reject('source_or_connection_unverified')
    if fingerprint(state)!=command.expected_fingerprint or state['connection_version']!=command.expected_connection_version:
        reject('review_changed')
    if reason in {'ambiguous_source','source_changed','quoted_source_unavailable','unsupported_source'} or state['source']['shortcode']!=command.shortcode or state['source']['classification']=='unknown':
        reject('source_changed')
    matches=state['matches']
    if any(identity!=command.product_id for identity in matches):
        reject('mapping_conflict')
    try:
        async with db.begin_nested():
            product=(await db.execute(select(Product,mapping_digest()).where(Product.id==command.product_id,
                Product.seller_id==business_id,Product.active.is_(True)).with_for_update(nowait=True,of=Product)
                .execution_options(populate_existing=True))).one_or_none()
    except DBAPIError as error:
        if getattr(error.orig,'sqlstate',None)!='55P03':
            raise
        reject('catalogue_busy')
    await guard()
    if product is None:
        reject('product_unavailable')
    product,before_mapping=product
    reviewed_candidates={row['id']:row['name'] for row in state['candidates']}
    if product.id not in reviewed_candidates or reviewed_candidates[product.id]!=product.name:
        reject('product_review_changed')
    current_matches=await facts.exact_reel_products(db,business_id,reel_url=state['source']['url'])
    await guard()
    if current_matches is None or any(identity!=product.id for identity in current_matches):
        reject('mapping_conflict')
    # Everything below is staged atomically; no typed pre-mutation rejection.
    accepted_at=await db.scalar(select(func.transaction_timestamp()))
    product.reel_urls=list(dict.fromkeys([*(product.reel_urls or []),state['source']['url']]))
    await db.flush()
    accepted_mapping=await db.scalar(select(mapping_digest()).where(Product.id==product.id,Product.seller_id==business_id))
    context=deepcopy((message.payload or {})['reel_context'])
    context['references']=[{**context['references'][0],'status':'matched','products':[{'id':str(product.id),'name':product.name}]}]
    outbound=None
    if command.action=='link_and_resume' and reason is None:
        if not facts.enabled():
            reason='catalogue_authority_unavailable'
        else:
            observed=await facts.read_facts(db,business_id,product.id,reel=dict(reel_url=state['source']['url']))
            if observed is None:
                reason='catalogue_authority_unavailable'
            else:
                question=facts.reel_question(message.text)
                reply=facts.render(observed) if question=='[customer sent media]' or facts.factual_request(question) else facts.HANDOFF
                # Account lock serializes the prior-outbound check with canonical
                # ingress/queue. Never adopt queue_message's existing-row return.
                existing=await db.scalar(select(WhatsAppMessage.id).where(WhatsAppMessage.seller_id==business_id,
                    WhatsAppMessage.idempotency_key=='auto:reel:'+message.provider_message_id))
                if existing is not None:
                    reason='reply_already_attempted'
                else:
                    outbound=await wa.queue_message(db,account,contact,key='auto:reel:'+message.provider_message_id,text=reply,
                        context={'reel_context':context,'customer_text':message.text},activity_producer=wa.activity.AutomatedWhatsAppProducer.REEL_REVIEW)
    result=dict(mapping='saved',resume='queued' if outbound else 'not_requested' if command.action=='link_only' else 'held',
        reason=None if outbound else 'resume_not_requested' if command.action=='link_only' else reason or 'needs_manual_reply',
        outbound_id=str(outbound.id) if outbound else None,mapping_fingerprint=accepted_mapping)
    receipt=Command(id=uuid4(),business_id=business_id,actor_user_id=binding.user_id,actor_session_id=binding.session_id,
        actor_auth_version=binding.auth_version,idempotency_key=command.idempotency_key,action=command.action,request_hash=digest,
        inbound_message_id=message.id,contact_id=contact.id,phone_number_id=message.phone_number_id,waba_id=account.waba_id,
        provider_mid=message.provider_message_id,source_classification=state['source']['classification'],source_fingerprint=state['source_fingerprint'],
        quoted_message_id=state['quoted_id'],quoted_fingerprint=state['quoted_fingerprint'],shortcode=command.shortcode,source_url=state['source']['url'],
        product_id=product.id,connection_version=state['connection_version'],credential_fingerprint=state['credential'],
        recipient_fingerprint=state['recipient_fingerprint'],
        expected_fingerprint=command.expected_fingerprint,expected_mapping_fingerprint=before_mapping,accepted_mapping_fingerprint=accepted_mapping,
        reply_context=context,result=result,created_at=accepted_at)
    db.add(receipt); await db.flush()
    if outbound:
        db.add(Authorization(command_id=receipt.id,business_id=business_id,inbound_message_id=message.id,
            contact_id=contact.id,phone_number_id=message.phone_number_id,outbound_message_id=outbound.id))
    await db.flush()
    await guard()
    return receipt_view(receipt)


# One fresh final scalar, after fact regeneration/flush. No locks, model refresh,
# provider call or awaited authority check may follow a successful return.
FINAL_RESUME_SQL = """SELECT auth.outbound_message_id
FROM whatsapp_reel_authorizations auth
JOIN whatsapp_reel_commands c ON c.business_id=auth.business_id AND c.id=auth.command_id
JOIN whatsapp_messages src ON src.seller_id=auth.business_id AND src.id=auth.inbound_message_id
JOIN whatsapp_messages dst ON dst.seller_id=auth.business_id AND dst.id=auth.outbound_message_id
JOIN whatsapp_accounts account ON account.seller_id=auth.business_id
JOIN channel_connection_states control ON control.business_id=auth.business_id AND control.channel='whatsapp'
JOIN whatsapp_contacts contact ON contact.seller_id=auth.business_id AND contact.id=auth.contact_id
JOIN user_sessions session ON session.id=c.actor_session_id
JOIN users reviewer ON reviewer.id=c.actor_user_id
JOIN memberships member ON member.business_id=auth.business_id AND member.user_id=c.actor_user_id
JOIN businesses business ON business.id=auth.business_id
JOIN sellers seller ON seller.id=auth.business_id
JOIN products product ON product.seller_id=auth.business_id AND product.id=c.product_id
JOIN storefronts store ON store.seller_id=auth.business_id
JOIN catalogue_activations activation ON activation.business_id=auth.business_id AND activation.product_id=product.id
JOIN catalogue_product_mappings mapping ON mapping.business_id=auth.business_id AND mapping.product_id=product.id
LEFT JOIN whatsapp_messages quoted ON quoted.seller_id=auth.business_id AND quoted.id=c.quoted_message_id
WHERE auth.outbound_message_id=:outbound_id AND auth.business_id=:business_id AND auth.contact_id=:contact_id
AND c.action='link_and_resume' AND c.result->>'resume'='queued' AND c.result->>'outbound_id'=dst.id::text
AND c.source_classification IN ('message_link','referral_link','quoted_message')
AND ROW(c.inbound_message_id,c.contact_id,c.phone_number_id)=ROW(auth.inbound_message_id,auth.contact_id,auth.phone_number_id)
AND ROW(src.contact_id,src.phone_number_id)=ROW(auth.contact_id,auth.phone_number_id)
AND src.direction='inbound' AND src.provider_message_id=c.provider_mid
AND wa_reel_source_fingerprint(src.payload,src.text,src.kind,src.created_at,src.provider_message_id,src.contact_id,src.phone_number_id)=c.source_fingerprint
AND src.payload->'reel_context'->>'source'=c.source_classification
AND src.created_at>clock_timestamp()-interval '24 hours' AND src.created_at<=clock_timestamp()
AND (c.quoted_message_id IS NULL OR (quoted.contact_id=contact.id AND quoted.phone_number_id=c.phone_number_id
AND quoted.provider_message_id=src.payload->>'reply_to_message_id'
AND wa_reel_source_fingerprint(quoted.payload,quoted.text,quoted.kind,quoted.created_at,quoted.provider_message_id,quoted.contact_id,quoted.phone_number_id)=c.quoted_fingerprint))
AND session.user_id=c.actor_user_id AND session.auth_version=c.actor_auth_version AND reviewer.auth_version=c.actor_auth_version
AND session.revoked_at IS NULL AND session.expires_at>clock_timestamp() AND reviewer.is_active AND reviewer.revoked_at IS NULL
AND member.is_active AND member.revoked_at IS NULL AND member.role IN ('owner','manager') AND business.is_active AND seller.is_active
AND account.phone_number_id=c.phone_number_id AND account.waba_id=c.waba_id AND account.access_token<>''
AND account.enabled AND account.automation_enabled AND account.reel_replies_enabled AND control.automation_enabled AND control.version=c.connection_version
AND encode(sha256(convert_to(account.access_token,'UTF8')),'hex')=c.credential_fingerprint
AND encode(sha256(convert_to(contact.phone,'UTF8')),'hex')=c.recipient_fingerprint
AND NOT contact.opted_out AND contact.last_inbound_at>clock_timestamp()-interval '24 hours' AND contact.last_inbound_at<=clock_timestamp()
AND product.active AND product.name=:product_name
AND product.name=c.reply_context->'references'->0->'products'->0->>'name' AND store.published AND mapping.state='reviewed'
AND mapping.revision=:mapping_revision AND mapping.revision>=activation.reviewed_revision
AND encode(sha256(convert_to(coalesce(product.reel_urls,'[]'::jsonb)::text,'UTF8')),'hex')=c.accepted_mapping_fingerprint
AND (SELECT count(*) FROM products candidate WHERE candidate.seller_id=auth.business_id AND candidate.active
AND EXISTS(SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(candidate.reel_urls)='array' THEN candidate.reel_urls ELSE '[]'::jsonb END) link
WHERE jsonb_typeof(link)='string' AND link#>>'{}' ~ :reference_pattern))=1
AND EXISTS(SELECT 1 FROM jsonb_array_elements(product.reel_urls) link WHERE jsonb_typeof(link)='string' AND link#>>'{}' ~ :reference_pattern)
AND (SELECT jsonb_agg(jsonb_build_object('sku_id',sku.id,'options',sku.options,'price_minor',sku.price_minor,
'currency',sku.currency,'stock_available',sku.stock_available) ORDER BY sku.id)
FROM catalogue_skus sku WHERE sku.business_id=auth.business_id AND sku.product_id=product.id AND sku.active)=CAST(:expected_skus AS jsonb)
AND dst.contact_id=auth.contact_id AND dst.phone_number_id=c.phone_number_id AND dst.direction='outbound' AND dst.kind='text'
AND dst.idempotency_key='auto:reel:' || c.provider_mid AND dst.status IN ('queued','sending') AND dst.provider_message_id IS NULL
AND dst.text=:expected_text AND dst.payload=jsonb_build_object('reel_context',c.reply_context,'customer_text',src.text)
AND NOT EXISTS(SELECT 1 FROM whatsapp_messages newer WHERE newer.seller_id=auth.business_id AND newer.contact_id=auth.contact_id
AND newer.direction='inbound' AND newer.created_at>=src.created_at AND newer.id<>src.id)
AND NOT EXISTS(SELECT 1 FROM whatsapp_messages attempted WHERE attempted.seller_id=auth.business_id AND attempted.contact_id=auth.contact_id
AND attempted.direction='outbound' AND attempted.id<>dst.id AND attempted.created_at>=src.created_at)
AND lower(btrim(src.text)) NOT IN ('stop','unsubscribe','start')
"""


async def revalidate_resume(db,account,contact,message) -> None:
    # Lookup by globally unique outbound UUID first. A wrongly supplied tenant or
    # contact must not turn a bound resume into an ordinary unbound message.
    accepted=(await db.execute(select(Command).join(Authorization,
        (Authorization.command_id==Command.id)&(Authorization.business_id==Command.business_id)).where(
        Authorization.outbound_message_id==message.id).execution_options(autoflush=False,populate_existing=True))).scalar_one_or_none()
    if accepted is None:
        # Approved unconditional installation: keep an existing0057 exact test's
        # own final scalar LAST inside this outer guard. Never branch on or use
        # its returned authorization object as a send exception.
        from app.services.whatsapp_test_authority import exact_test_authority
        await exact_test_authority(db,account,contact,message)
        return None
    def held():
        raise HTTPException(409,'The reviewed reel reply is no longer eligible; review its current source')
    if not settings.V1_AUTH_ENABLED or not facts.enabled() or (account.seller_id,contact.id,message.seller_id)!=(accepted.business_id,accepted.contact_id,accepted.business_id):
        held()
    observed=await facts.read_facts(db,accepted.business_id,accepted.product_id,reel=dict(reel_url=accepted.source_url))
    if observed is None:
        held()
    question=facts.reel_question((message.payload or {}).get('customer_text',''))
    current=facts.render(observed) if question=='[customer sent media]' or facts.factual_request(question) else facts.HANDOFF
    message.text=current
    await db.flush()
    expected_skus=[sku.model_dump(mode='json') for sku in sorted(observed.skus,key=lambda sku:str(sku.sku_id))]
    pattern=r'^[hH][tT][tT][pP][sS]?://([wW][wW][wW]\.|[mM]\.)?[iI][nN][sS][tT][aA][gG][rR][aA][mM]\.[cC][oO][mM]/(reel|reels|p|tv)/'+re.escape(accepted.shortcode)+r'/?([?#][^\s]*)?$'
    allowed=await db.scalar(text(FINAL_RESUME_SQL).execution_options(autoflush=False),dict(
        outbound_id=message.id,business_id=account.seller_id,contact_id=contact.id,
        product_name=observed.product_name,mapping_revision=observed.mapping_revision,
        reference_pattern=pattern,expected_text=current,expected_skus=json.dumps(expected_skus,sort_keys=True,separators=(',',':'))))
    if allowed!=message.id or not settings.V1_AUTH_ENABLED or not facts.enabled():
        held()
    return None
