"""Existing-member onboarding ownership; assignments never grant access."""
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from app.database import Base


class OnboardingAssignment(Base):
    __tablename__ = 'v1_onboarding_assignments'
    business_id = Column(UUID(as_uuid=True), ForeignKey('businesses.id', ondelete='RESTRICT'), primary_key=True)
    assignee_user_id = Column(UUID(as_uuid=True), nullable=True)
    assigned_by_user_id = Column(UUID(as_uuid=True), nullable=False)
    version = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(['business_id','assignee_user_id'], ['memberships.business_id','memberships.user_id'], name='v1_assistance_assignee_member', ondelete='RESTRICT'),
        ForeignKeyConstraint(['business_id','assigned_by_user_id'], ['memberships.business_id','memberships.user_id'], name='v1_assistance_assigner_member', ondelete='RESTRICT'),
        CheckConstraint('version > 0 AND version <= 2000000000', name='v1_assistance_assignment_version'),
    )


class AssistanceCommand(Base):
    __tablename__ = 'v1_assistance_commands'
    business_id = Column(UUID(as_uuid=True), ForeignKey('businesses.id', ondelete='RESTRICT'), primary_key=True)
    idempotency_key = Column(UUID(as_uuid=True), primary_key=True)
    actor_user_id = Column(UUID(as_uuid=True), nullable=False)
    operation = Column(String(20), nullable=False)
    request_hash = Column(String(64), nullable=False)
    result = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(['business_id','actor_user_id'], ['memberships.business_id','memberships.user_id'], name='v1_assistance_command_actor_member', ondelete='RESTRICT'),
        CheckConstraint("operation IN ('assignment','open')", name='v1_assistance_command_operation'),
        CheckConstraint("request_hash ~ '^[a-f0-9]{64}$' AND jsonb_typeof(result)='object'", name='v1_assistance_command_result'),
    )
