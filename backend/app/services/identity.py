"""V1 identity bridge and server-authoritative membership capabilities.

No function issues legacy seller tokens or commits its caller's transaction.
"""
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.identity import Business, Membership, User
from app.models.seller import Seller

_READ = frozenset({"business.read", "readiness.read", "catalogue.read", "orders.read", "inbox.read", "analytics.read"})
_MANAGER = _READ | {"business.write", "catalogue.write", "orders.write", "inbox.reply", "automation.manage"}
ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "owner": _MANAGER | {"channels.connect", "channels.disconnect", "members.manage"},
    "manager": _MANAGER,
    "staff": frozenset({"business.read", "readiness.read", "catalogue.read", "orders.read", "orders.write", "inbox.read", "inbox.reply"}),
    "viewer": _READ,
}


def capabilities_for(role: str) -> frozenset[str]:
    return ROLE_CAPABILITIES.get(role, frozenset())


def legacy_owner_id(seller_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"munimjee:v1:legacy-owner:{seller_id}")


def legacy_membership_id(seller_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"munimjee:v1:legacy-owner-membership:{seller_id}")


@dataclass(frozen=True)
class Actor:
    user_id: UUID
    auth_method: str


@dataclass(frozen=True)
class BusinessAccess:
    business: Business
    membership: Membership
    seller: Seller

    @property
    def capabilities(self) -> frozenset[str]:
        return capabilities_for(self.membership.role)


class IdentityBridgeConflict(RuntimeError):
    """An existing identity disagrees with the immutable legacy mapping."""


async def ensure_legacy_owner_bridge(db: AsyncSession, seller: Seller) -> None:
    """Insert missing rows only, including from a future signup transaction.

    Never resets an inactive user/business or a revoked/changed membership.
    """
    if seller.id is None:
        raise ValueError("Flush the seller before creating its identity bridge")
    uid = legacy_owner_id(seller.id)
    await db.execute(insert(Business).values(id=seller.id, name=seller.business_name or seller.email,
                                           is_active=bool(seller.is_active)).on_conflict_do_nothing())
    await db.execute(insert(User).values(id=uid, legacy_seller_id=seller.id,
                                       display_name=seller.business_name, is_active=bool(seller.is_active)).on_conflict_do_nothing())
    user = await db.get(User, uid)
    if user is None or user.legacy_seller_id != seller.id:
        raise IdentityBridgeConflict("Legacy seller has a conflicting user mapping")
    await db.execute(insert(Membership).values(id=legacy_membership_id(seller.id), business_id=seller.id,
                                              user_id=uid, role="owner", is_active=bool(seller.is_active)).on_conflict_do_nothing())
    membership = (await db.execute(select(Membership).where(Membership.business_id == seller.id,
                                                           Membership.user_id == uid))).scalar_one_or_none()
    if membership is None:
        raise IdentityBridgeConflict("Legacy seller has a conflicting membership mapping")


async def backfill_legacy_owners(db: AsyncSession) -> int:
    """Reconcile all sellers without committing; return scanned count, not grants."""
    count = 0
    result = await db.stream_scalars(select(Seller).order_by(Seller.id))
    async for seller in result:
        await ensure_legacy_owner_bridge(db, seller)
        count += 1
    return count


async def resolve_user_actor(db: AsyncSession, user_id: UUID, auth_method: str) -> Actor:
    user = await db.get(User, user_id)
    if user is None or not user.is_active or user.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Active user login required")
    return Actor(user_id=user.id, auth_method=auth_method)


async def resolve_legacy_owner(db: AsyncSession, seller_id: UUID) -> Actor:
    seller = await db.get(Seller, seller_id)
    if seller is None or not seller.is_active:
        raise HTTPException(status_code=401, detail="Active seller login required")
    uid = legacy_owner_id(seller.id)
    actor = await resolve_user_actor(db, uid, "legacy_owner")
    user = await db.get(User, uid)
    if user.legacy_seller_id != seller.id:
        raise HTTPException(status_code=401, detail="Legacy owner identity unavailable")
    access = await require_business_access(db, actor, seller.id)
    if access.membership.role != "owner":
        raise HTTPException(status_code=403, detail="Legacy owner membership required")
    return actor


async def accessible_businesses(db: AsyncSession, actor: Actor) -> list[BusinessAccess]:
    await resolve_user_actor(db, actor.user_id, actor.auth_method)
    rows = (await db.execute(select(Business, Membership, Seller).join(
        Membership, Membership.business_id == Business.id).join(Seller, Seller.id == Business.id).where(
            Membership.user_id == actor.user_id, Membership.is_active.is_(True), Membership.revoked_at.is_(None),
            Membership.role.in_(tuple(ROLE_CAPABILITIES)), Business.is_active.is_(True), Seller.is_active.is_(True)
        ).order_by(Business.id))).all()
    return [BusinessAccess(business, membership, seller) for business, membership, seller in rows]


async def require_business_access(db: AsyncSession, actor: Actor, business_id: UUID,
                                  capability: str = "business.read") -> BusinessAccess:
    await resolve_user_actor(db, actor.user_id, actor.auth_method)
    row = (await db.execute(select(Business, Membership, Seller).join(
        Membership, Membership.business_id == Business.id).join(Seller, Seller.id == Business.id).where(
            Business.id == business_id, Membership.user_id == actor.user_id,
            Membership.is_active.is_(True), Membership.revoked_at.is_(None),
            Business.is_active.is_(True), Seller.is_active.is_(True)
        ))).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Business not found")
    access = BusinessAccess(*row)
    if capability not in access.capabilities:
        raise HTTPException(status_code=403, detail="Capability required")
    return access
