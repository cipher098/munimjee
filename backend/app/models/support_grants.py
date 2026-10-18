"""Explicit owner consent; these records never create a membership."""
from uuid import uuid4
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from app.database import Base


class SupportGrant(Base):
    __tablename__ = 'v1_support_grants'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey('businesses.id', ondelete='RESTRICT'), nullable=False)
    subject_user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    consented_by_user_id = Column(UUID(as_uuid=True), nullable=False)
    subject_auth_version = Column(Integer, nullable=False)
    owner_auth_version = Column(Integer, nullable=False)
    scope = Column(String(40), nullable=False)
    reason = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id = Column(UUID(as_uuid=True), nullable=True)
    __table_args__ = (
        UniqueConstraint('business_id','id',name='v1_support_grant_tenant'),
        ForeignKeyConstraint(['business_id','consented_by_user_id'],['memberships.business_id','memberships.user_id'],name='v1_support_grant_owner',ondelete='RESTRICT'),
        ForeignKeyConstraint(['business_id','revoked_by_user_id'],['memberships.business_id','memberships.user_id'],name='v1_support_grant_revoker',ondelete='RESTRICT'),
        CheckConstraint("scope='readiness.summary' AND char_length(reason) BETWEEN 1 AND 200",name='v1_support_grant_scope'),
        CheckConstraint('subject_auth_version>=0 AND owner_auth_version>=0 AND subject_user_id<>consented_by_user_id',name='v1_support_grant_subject'),
        CheckConstraint("expires_at>=created_at+interval '5 minutes' AND expires_at<=created_at+interval '60 minutes'",name='v1_support_grant_expiry'),
        CheckConstraint('(revoked_at IS NULL)=(revoked_by_user_id IS NULL) AND (revoked_at IS NULL OR revoked_at>=created_at)',name='v1_support_grant_revocation'),
        Index('v1_support_grant_subject_lookup','subject_user_id','business_id','expires_at'),
    )


class SupportCommand(Base):
    __tablename__ = 'v1_support_commands'
    business_id = Column(UUID(as_uuid=True), ForeignKey('businesses.id',ondelete='RESTRICT'),primary_key=True)
    idempotency_key = Column(UUID(as_uuid=True),primary_key=True)
    grant_id = Column(UUID(as_uuid=True),nullable=False)
    actor_user_id = Column(UUID(as_uuid=True),ForeignKey('users.id',ondelete='RESTRICT'),nullable=False)
    operation = Column(String(20),nullable=False)
    request_hash = Column(String(64),nullable=False)
    result = Column(JSONB,nullable=False)
    created_at = Column(DateTime(timezone=True),nullable=False,server_default=func.clock_timestamp())
    __table_args__ = (
        ForeignKeyConstraint(['business_id','grant_id'],['v1_support_grants.business_id','v1_support_grants.id'],name='v1_support_command_grant',ondelete='RESTRICT'),
        CheckConstraint("operation IN ('create','revoke','open')",name='v1_support_command_operation'),
        CheckConstraint("request_hash ~ '^[a-f0-9]{64}$' AND jsonb_typeof(result)='object'",name='v1_support_command_result'),
    )
