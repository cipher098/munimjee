"""Transactional native signup, credential migration, invites and business profile."""
import secrets
from datetime import timedelta
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy import func, select
from app.models.identity import Business, Membership, User
from app.models.identity_auth import BusinessInvitation, IdentityAuditEvent
from app.models.seller import Seller
from app.schemas.identity_auth import InvitationAcceptInput, ProfileInput, SignupInput
from app.services.auth_sessions import now_utc, secret_digest
from app.services.identity import (Actor, ensure_legacy_owner_bridge, legacy_owner_id,
                                  require_business_access, resolve_user_actor)


def normalize_email(value) -> str:
    return str(value).strip().casefold()


def audit(db, actor_id, event_type, *, business_id=None, subject_id=None, details=None):
    db.add(IdentityAuditEvent(actor_user_id=actor_id, business_id=business_id,
        event_type=event_type, subject_id=subject_id, details=details or {}))


async def authenticate(db, email, password: str) -> User:
    from app.api.routes.auth import _verify_password
    key = normalize_email(email)
    user = await db.scalar(select(User).where(User.auth_email == key))
    if user is not None:
        if not user.password_hash or not _verify_password(password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        await resolve_user_actor(db, user.id, "v1_user")
        return user
    # Only possession of the existing password links the legacy credential.
    # Email equality is lookup, never sufficient identity-link evidence.
    sellers = (await db.scalars(select(Seller).where(func.lower(Seller.email) == key).limit(2))).all()
    if len(sellers) != 1 or not sellers[0].is_active or not _verify_password(password, sellers[0].password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    seller = sellers[0]
    user = await db.get(User, legacy_owner_id(seller.id))
    if user is None or user.legacy_seller_id != seller.id:
        raise HTTPException(status_code=401, detail="Account requires an identity upgrade")
    await resolve_user_actor(db, user.id, "v1_user")
    user.auth_email, user.password_hash = key, seller.password_hash
    audit(db, user.id, "legacy_credential_linked")
    await db.flush()
    return user


async def signup(db, body: SignupInput) -> User:
    from app.api.routes.auth import _hash_password
    from app.seller_defaults import DEFAULT_PERSONA, DEFAULT_POLICIES
    key = normalize_email(body.email)
    if (await db.scalar(select(User.id).where(User.auth_email == key)) is not None
            or await db.scalar(select(Seller.id).where(func.lower(Seller.email) == key).limit(1)) is not None):
        raise HTTPException(status_code=409, detail="Email already registered; sign in instead")
    hashed = _hash_password(body.password)
    seller = Seller(id=uuid4(), email=key, password_hash=hashed, business_name=body.business_name,
                    onboarding_state="signed_up", is_active=True,
                    persona=DEFAULT_PERSONA, policies=DEFAULT_POLICIES)
    db.add(seller)
    await db.flush()
    # Same caller-owned transaction: failed bridge/session setup cannot leave
    # an account committed without its membership.
    await ensure_legacy_owner_bridge(db, seller)
    user = await db.get(User, legacy_owner_id(seller.id))
    user.auth_email, user.password_hash = key, hashed
    audit(db, user.id, "signup", business_id=seller.id)
    await db.flush()
    return user


async def save_profile(db, actor: Actor, business_id: UUID, body: ProfileInput) -> Business:
    await require_business_access(db, actor, business_id, "business.write")
    business = await db.scalar(select(Business).where(Business.id == business_id).with_for_update(key_share=True)
        .execution_options(populate_existing=True))
    if business.profile_version != body.expected_version:
        raise HTTPException(status_code=409, detail="Business details changed; refresh before saving")
    business.name = body.name
    business.profile = body.model_dump(mode="json", exclude={"expected_version", "name"})
    business.profile_version += 1
    business.profile_confirmed_at = now_utc()
    seller = await db.get(Seller, business_id)
    seller.business_name = business.name
    audit(db, actor.user_id, "business_profile_updated", business_id=business_id,
          details={"profile_version": business.profile_version})
    await db.flush()
    return business


async def create_invitation(db, actor: Actor, business_id: UUID, email, role: str):
    await require_business_access(db, actor, business_id, "members.manage")
    if role not in {"manager", "staff", "viewer"}:
        raise HTTPException(status_code=422, detail="Invalid invitation role")
    secret = secrets.token_urlsafe(32)
    invitation = BusinessInvitation(id=uuid4(), business_id=business_id, created_by=actor.user_id,
        auth_email=normalize_email(email), role=role, token_digest=secret_digest(secret),
        expires_at=now_utc() + timedelta(days=7))
    db.add(invitation)
    audit(db, actor.user_id, "invitation_created", business_id=business_id,
          subject_id=invitation.id, details={"role": role})
    await db.flush()
    return invitation, secret


async def accept_invitation(db, body: InvitationAcceptInput) -> User:
    from app.api.routes.auth import _hash_password
    row = await db.scalar(select(BusinessInvitation).where(
        BusinessInvitation.token_digest == secret_digest(body.token)).with_for_update())
    if (row is None or row.consumed_at is not None or row.revoked_at is not None
            or row.expires_at <= now_utc() or row.auth_email != normalize_email(body.email)):
        raise HTTPException(status_code=400, detail="Invitation is invalid, expired or already used")
    # Inviter must still have owner authority at consumption time.
    inviter = Actor(row.created_by, "v1_user")
    await require_business_access(db, inviter, row.business_id, "members.manage")
    key = row.auth_email
    user = await db.scalar(select(User).where(User.auth_email == key))
    legacy = await db.scalar(select(Seller.id).where(func.lower(Seller.email) == key).limit(1))
    if user is not None or legacy is not None:
        # Never merge an existing account solely because the invitation email matches.
        user = await authenticate(db, body.email, body.password)
    else:
        user = User(id=uuid4(), auth_email=key, password_hash=_hash_password(body.password), is_active=True)
        db.add(user)
        await db.flush()
    membership = await db.scalar(select(Membership).where(
        Membership.business_id == row.business_id, Membership.user_id == user.id).with_for_update())
    if membership is not None:
        raise HTTPException(status_code=409, detail="Membership already exists; ask the owner to review access")
    db.add(Membership(id=uuid4(), business_id=row.business_id, user_id=user.id, role=row.role, is_active=True))
    row.consumed_at, row.accepted_by = now_utc(), user.id
    audit(db, user.id, "invitation_accepted", business_id=row.business_id,
          subject_id=row.id, details={"role": row.role})
    await db.flush()
    return user


async def revoke_membership(db, actor: Actor, business_id: UUID, membership_id: UUID):
    await require_business_access(db, actor, business_id, "members.manage")
    row = await db.scalar(select(Membership).where(Membership.id == membership_id,
        Membership.business_id == business_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    if row.role == "owner":
        raise HTTPException(status_code=409, detail="Owner transfer is a separate operation")
    row.is_active, row.revoked_at = False, now_utc()
    audit(db, actor.user_id, "membership_revoked", business_id=business_id, subject_id=row.id)
    await db.flush()
    return row
