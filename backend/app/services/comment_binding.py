"""Fresh scalar comment policy snapshots. No catalogue row locks or provider I/O."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from sqlalchemy import and_, exists, func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from app.config import settings
from app.models.identity import Business
from app.models.seller import Seller
from app.models.channel_operator import ChannelConnectionState as Control
from app.models.comment_automation import CommentRule, CommentAction
from app.models.product import Product
from app.models.commerce import Storefront
from app.models.checkout_v1 import CatalogueActivation
from app.services.instagram_credentials import Connection
from app.schemas.comment_binding import digest, source_age_reason, valid_claim


@dataclass(frozen=True)
class Context:
    connection: Connection
    automation_enabled: bool
    config: dict = field(repr=False)
    rule: dict = field(repr=False)
    rules: tuple = field(repr=False)
    product_available: bool
    activated: bool
    published: bool
    claim_active: bool = True

    def source_reason(self):
        if not self.connection.active:return 'business_unavailable'
        if not self.connection.usable():return 'source_binding_unavailable'
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',self.connection.account_id) or not re.fullmatch(r'[\x21-\x7e]{1,4096}',self.connection.token):
            return 'source_binding_unavailable'
        if not self.automation_enabled:return 'automation_paused'
        control=self.config.get('control',{})
        if control.get('check_status')!='verified' or not control.get('checked_at'):return 'account_access_not_checked'
        if not settings.META_WEBHOOK_SECRET:return 'configuration_unavailable'
        return None


def matched_rules(rules, text, media_id):
    from app.services.comment_automation import matches
    if len(rules)>100:raise ValueError('Rule scope is unbounded')
    result=[]
    for rule in rules:
        if (type(rule) is not dict or type(rule.get('keywords')) is not list or not 1<=len(rule['keywords'])<=30
            or any(not isinstance(k,str) or not k.strip() or len(k)>60 for k in rule['keywords'])):
            raise ValueError('Rule scope is invalid')
        from types import SimpleNamespace
        if matches(SimpleNamespace(**rule),text,media_id):result.append(rule)
    return result


def source_config(current):
    return {key:current.config.get(key) for key in ('scopes','control','origin','api_version','webhook_key_hash','owner_account')}


async def context(db,business_id,rule_id=None,*,action_id=None,claim_token=None):
    # One SQL snapshot includes source/control/rule/product/store and all bounded
    # rule scopes. No retained ORM object authorizes a send after claim commit.
    scopes=select(CommentRule.id,CommentRule.product_id,CommentRule.media_id,CommentRule.keywords,CommentRule.private_reply,CommentRule.public_reply,CommentRule.created_at).where(
        CommentRule.seller_id==Seller.id,CommentRule.enabled.is_(True)).order_by(CommentRule.created_at,CommentRule.id).limit(101).correlate(Seller).subquery()
    rules=select(func.jsonb_agg(aggregate_order_by(func.jsonb_build_object('id',scopes.c.id,'product_id',scopes.c.product_id,
        'media_id',scopes.c.media_id,'keywords',scopes.c.keywords,'private_reply',scopes.c.private_reply,'public_reply',scopes.c.public_reply),scopes.c.created_at,scopes.c.id))).select_from(scopes).scalar_subquery()
    active=exists(select(CatalogueActivation.product_id).where(CatalogueActivation.business_id==Seller.id,
        CatalogueActivation.product_id==Product.id)).correlate(Seller,Product)
    claim_active=exists(select(CommentAction.id).where(CommentAction.id==action_id,CommentAction.seller_id==business_id,
        CommentAction.claim_token==claim_token,CommentAction.status=='sending')) if action_id is not None else True
    query=select(Seller.instagram_page_id.label('account'),Seller.instagram_id.label('owner_account'),Seller.instagram_token.label('token'),
        Seller.instagram_token_expires_at.label('expiry'),Control.version,Control.provider_account_id,Control.automation_enabled,
        Control.check_status,Control.checked_at,Control.error_code,Business.is_active.label('business_active'),Seller.is_active.label('seller_active'),
        CommentRule.id.label('rule_id'),CommentRule.enabled.label('rule_enabled'),CommentRule.media_id.label('rule_media'),
        CommentRule.keywords,CommentRule.product_id,CommentRule.private_reply,CommentRule.public_reply,
        Product.active.label('product_active'),Product.name,Product.listed_price,Product.variants,Product.description,Product.stock_quantity,Product.photo_url,Product.photo_urls,Product.reel_urls,
        Storefront.slug,Storefront.published,active.label('activated'),rules.label('scopes'),func.coalesce(claim_active,False).label('claim_active')).select_from(Seller).join(
        Business,Business.id==Seller.id).outerjoin(Control,and_(Control.business_id==Seller.id,Control.channel=='instagram')).outerjoin(
        CommentRule,and_(CommentRule.seller_id==Seller.id,CommentRule.id==rule_id)).outerjoin(Product,and_(
        Product.id==CommentRule.product_id,Product.seller_id==Seller.id)).outerjoin(Storefront,Storefront.seller_id==Seller.id).where(
        Seller.id==business_id).execution_options(autoflush=False)
    with db.no_autoflush:
        row=(await db.execute(query)).mappings().one_or_none()
    if row is None:return None
    connection=Connection(row['account'],row['token'],row['expiry'],row['version'] if row['version'] is not None else -1,
        row['provider_account_id'],bool(row['business_active'] and row['seller_active']))
    rule={'id':str(row['rule_id']) if row['rule_id'] else None,'enabled':row['rule_enabled'],'media_id':row['rule_media'],
        'keywords':row['keywords'],'product_id':str(row['product_id']) if row['product_id'] else None,
        'private_reply':row['private_reply'],'public_reply':row['public_reply']}
    config={'rule':rule,'product':{'active':row['product_active'],'name':row['name'],'listed_price':row['listed_price'],
        'variants':row['variants'],'stock_quantity':row['stock_quantity'],'media_hash':digest([row['photo_url'],row['photo_urls'],row['reel_urls']]),'description_hash':digest(row['description'])},
        'store':{'slug':row['slug'],'published':row['published']},'scopes':row['scopes'] or [],
        'control':{'automation_enabled':row['automation_enabled'],'version':row['version'],'bound_account':row['provider_account_id'],
            'check_status':row['check_status'],'checked_at':row['checked_at'].isoformat() if row['checked_at'] else None,'error_code':row['error_code']},
        'owner_account':row['owner_account'],'origin':settings.PUBLIC_BASE_URL.rstrip('/'),'api_version':settings.META_API_VERSION,
        'webhook_key_hash':digest(settings.META_WEBHOOK_SECRET)}
    return Context(connection,bool(row['automation_enabled']),config,rule,tuple(row['scopes'] or []),
        bool(row['product_active']),bool(row['activated']),bool(row['published']),bool(row['claim_active']))


def eligibility(current,event,action=None):
    if current is None:return 'business_unavailable'
    reason=current.source_reason()
    if reason:return reason
    if not current.connection.matches(event.source_binding) or current.connection.account_id!=event.source_account_id:
        return 'source_generation_changed'
    reason=source_age_reason(event.commented_at)
    if reason:return reason
    if not current.rule.get('id') or not current.rule.get('enabled'):return 'rule_configuration_changed'
    if not current.product_available or not current.published:return 'product_context_unavailable'
    if current.rule.get('media_id')!=event.media_id:return 'product_context_unbound'
    if current.activated:return 'activated_context_requires_review'
    try:
        rules=matched_rules(current.rules,event.text,event.media_id)
        if len({r['product_id'] for r in rules})>1:return 'product_context_ambiguous'
        if str(event.rule_id) not in {r['id'] for r in rules}:return 'rule_configuration_changed'
    except (TypeError,ValueError,AttributeError):return 'rule_scope_unavailable'
    from app.services.comment_automation import public_base_ready
    if not public_base_ready():return 'configuration_unavailable'
    if action is not None:
        if not valid_claim(action,event):return 'accepted_claim_invalid'
        if action.accepted_claim['config_hash']!=digest(current.config):return 'rule_configuration_changed'
    return None
