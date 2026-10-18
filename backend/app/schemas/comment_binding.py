"""Private comment acceptance fingerprints; never a browser verification contract."""
import hashlib
import hmac
import json
from datetime import datetime, timezone
from app.config import settings

SOURCE_CHECK = """(source_account_id IS NULL AND source_binding IS NULL AND source_verified_at IS NULL AND source_verification IS NULL) OR coalesce((
 source_account_id IS NOT NULL AND source_verified_at IS NOT NULL AND source_verification IN ('signed_webhook','provider_metadata')
 AND jsonb_typeof(source_binding)='object' AND octet_length(source_binding::text)<=2048
 AND source_binding ?& ARRAY['account_id','version','credential_hash','expires_at']
 AND source_binding-ARRAY['account_id','version','credential_hash','expires_at']='{}'::jsonb
 AND jsonb_typeof(source_binding->'account_id')='string' AND source_binding->>'account_id'=source_account_id
 AND length(source_account_id) BETWEEN 1 AND 100
 AND jsonb_typeof(source_binding->'version')='number' AND source_binding->>'version' ~ '^(0|[1-9][0-9]{0,8})$'
 AND jsonb_typeof(source_binding->'credential_hash')='string' AND source_binding->>'credential_hash' ~ '^[a-f0-9]{64}$'
 AND jsonb_typeof(source_binding->'expires_at')='string' AND length(source_binding->>'expires_at') BETWEEN 10 AND 80
),false)"""
CLAIM_CHECK = """(accepted_claim IS NULL AND claim_hash IS NULL) OR coalesce((
 jsonb_typeof(accepted_claim)='object' AND octet_length(accepted_claim::text)<=4096
 AND claim_hash ~ '^[a-f0-9]{64}$'
),false)"""

CLAIM_STATE_CHECK = """accepted_claim IS NULL OR (
 (claim_token IS NULL AND attempted_at IS NULL AND provider_id IS NULL AND status IN ('pending','review_required','cancelled'))
 OR (claim_token IS NOT NULL AND attempted_at IS NOT NULL AND status IN ('sending','sent','unknown','rejected','review_required','cancelled'))
)"""


def digest(value):
    encoded=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
    return hmac.new(settings.SECRET_KEY.encode(),b'comment-binding.v1:'+encoded,hashlib.sha256).hexdigest()


def valid_proof(value):
    if type(value) is not dict or set(value)!={'account_id','version','credential_hash','expires_at'}:
        return False
    import re
    if (not isinstance(value['account_id'],str) or not 1<=len(value['account_id'])<=100
        or type(value['version']) is not int or not 0<=value['version']<=999999999
        or not isinstance(value['credential_hash'],str) or not re.fullmatch('[a-f0-9]{64}',value['credential_hash'])):
        return False
    try:
        expiry=datetime.fromisoformat(value['expires_at'])
        return expiry.utcoffset() is not None and len(value['expires_at'])<=80
    except (TypeError,ValueError):
        return False


def event_facts(event):
    return {key:str(getattr(event,key)) if key in {'id','seller_id','rule_id'} else getattr(event,key)
        for key in ('id','seller_id','rule_id','comment_id','media_id','actor_id','text','source_account_id','source_verification')} | {
        'commented_at':event.commented_at.isoformat() if event.commented_at else None,
        'source_verified_at':event.source_verified_at.isoformat() if event.source_verified_at else None}


def accepted_claim(event, kind, body, config):
    return {'contract_version':'comment-action.v1','event_hash':digest(event_facts(event)),
        'connection':event.source_binding,'config_hash':digest(config),'body_hash':digest(body),'kind':kind}


def valid_claim(action,event):
    value=action.accepted_claim
    if not valid_proof(event.source_binding) or type(value) is not dict or set(value)!={'contract_version','event_hash','connection','config_hash','body_hash','kind'}:
        return False
    try:
        return (len(json.dumps(value))<=4096 and value['contract_version']=='comment-action.v1'
            and value['kind']==action.kind and action.kind in {'private','public'}
            and value['connection']==event.source_binding and value['connection']['account_id']==event.source_account_id
            and hmac.compare_digest(value['event_hash'],digest(event_facts(event)))
            and hmac.compare_digest(value['body_hash'],digest(action.body))
            and hmac.compare_digest(action.claim_hash,digest(value)))
    except (TypeError,ValueError):
        return False


def source_age_reason(timestamp, at=None):
    from datetime import timedelta
    at=at or datetime.now(timezone.utc)
    if not isinstance(timestamp,datetime) or timestamp.utcoffset() is None or timestamp>at+timedelta(minutes=5):
        return 'source_time_unverified'
    # Local conservative cutoff only; not proof of official provider entitlement.
    return 'source_too_old' if at-timestamp>=timedelta(days=7) else None
