"""Fresh Instagram connection generations shared by import and credential writers.

Callers own transactions. Lock Business -> Seller -> control; network work stays
outside these locks, and a delayed result is accepted only for its original proof.
"""
import hashlib
import hmac
from datetime import datetime, timezone
from dataclasses import dataclass, field
from sqlalchemy import select
from app.config import settings
from app.models.identity import Business
from app.models.seller import Seller
from app.models.channel_operator import ChannelConnectionState
from app.v1.imports.instagram_owned import OwnedCredentialSnapshot
from app.v1.imports.instagram_owned_transport import OwnedInstagramError


def fingerprint(token):
    return hmac.new(settings.SECRET_KEY.encode(), ('instagram-import:'+str(token or '')).encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Connection:
    account_id: str | None
    token: str | None = field(repr=False)
    expires_at: datetime | None
    version: int
    bound_account: str | None
    active: bool

    def proof(self):
        return {'account_id': self.account_id, 'version': self.version, 'credential_hash': fingerprint(self.token), 'expires_at':self.expires_at.isoformat() if self.expires_at else None}

    def matches(self, proof):
        return isinstance(proof, dict) and self.account_id == proof.get('account_id') and self.version == proof.get('version') and hmac.compare_digest(fingerprint(self.token), str(proof.get('credential_hash', ''))) and (self.expires_at.isoformat() if self.expires_at else None)==proof.get('expires_at')

    def usable(self):
        return bool(self.active and self.account_id and self.bound_account == self.account_id and self.token and self.expires_at and self.expires_at > datetime.now(timezone.utc))


async def snapshot(db, business_id, *, lock=False):
    with db.no_autoflush:
        if lock:
            await db.execute(select(Business.id).where(Business.id == business_id).with_for_update(key_share=True))
            await db.execute(select(Seller.id).where(Seller.id == business_id).with_for_update(key_share=True))
            await db.execute(select(ChannelConnectionState.business_id).where(ChannelConnectionState.business_id == business_id, ChannelConnectionState.channel == 'instagram').with_for_update())
        row = (await db.execute(select(Seller.instagram_page_id, Seller.instagram_token,
            Seller.instagram_token_expires_at, ChannelConnectionState.version, ChannelConnectionState.provider_account_id,
            Business.is_active, Seller.is_active).join(Business, Business.id == Seller.id).outerjoin(
            ChannelConnectionState, (ChannelConnectionState.business_id == Seller.id) & (ChannelConnectionState.channel == 'instagram')).where(
            Seller.id == business_id).execution_options(autoflush=False))).one_or_none()
    if row is None:
        return Connection(None, None, None, -1, None, False)
    return Connection(row[0], row[1], row[2], row[3] if row[3] is not None else -1, row[4], bool(row[5] and row[6]))


async def replace(db, business_id, *, expected, account_id, token, expires_at):
    current = await snapshot(db, business_id, lock=True)
    if not current.active or not current.matches(expected):
        return False
    state = await db.get(ChannelConnectionState, (business_id, 'instagram'), populate_existing=True)
    if current.account_id and current.account_id != account_id:
        return False
    if state and state.provider_account_id and state.provider_account_id != account_id:
        return False
    seller = await db.get(Seller, business_id, populate_existing=True)
    seller.instagram_id = seller.instagram_page_id = seller.fb_page_id = account_id
    seller.instagram_token, seller.instagram_token_expires_at = token, expires_at
    if state is None:
        state = ChannelConnectionState(business_id=business_id, channel='instagram', version=0,
            provider_account_id=account_id, automation_enabled=False, check_status='not_checked')
        db.add(state)
    state.version += 1
    state.provider_account_id = account_id
    state.checked_at, state.check_status, state.error_code = None, 'not_checked', None
    return True


def credential(current, business_id, account_id, proof):
    if not current.usable() or current.account_id != account_id or not current.matches(proof):
        raise OwnedInstagramError('instagram_binding_changed')
    return OwnedCredentialSnapshot(business_id, account_id, current.token, current.expires_at, current.version)
