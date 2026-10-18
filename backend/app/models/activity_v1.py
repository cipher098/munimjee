"""Minimal first-party measurement; canonical order/payment facts stay separate."""
from uuid import uuid4
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from app.database import Base
# Actual tenant keys are already introduced by 0041/0044.
from app.models.checkout_v1 import CommerceOrder  # noqa: F401

CLASSIFICATION = "classification IN ('live','test','unknown')"


class ActivityPolicy(Base):
    __tablename__='v1_activity_policies'
    business_id=Column(UUID(as_uuid=True),ForeignKey('businesses.id'),primary_key=True)
    mode=Column(String(8),nullable=False)
    revision=Column(Integer,nullable=False)
    updated_at=Column(DateTime(timezone=True),nullable=False,server_default=func.clock_timestamp())
    __table_args__=(CheckConstraint("mode IN ('off','test','live') AND revision>=1",name='v1_activity_policy_value'),)


class ActivityPolicyCommand(Base):
    __tablename__='v1_activity_policy_commands'
    business_id=Column(UUID(as_uuid=True),ForeignKey('businesses.id'),primary_key=True)
    idempotency_key=Column(UUID(as_uuid=True),primary_key=True)
    actor_user_id=Column(UUID(as_uuid=True),ForeignKey('users.id'),nullable=False)
    request_hash=Column(String(64),nullable=False)
    mode=Column(String(8),nullable=False)
    revision=Column(Integer,nullable=False)
    notice_version=Column(String(30),nullable=False)
    created_at=Column(DateTime(timezone=True),nullable=False,server_default=func.clock_timestamp())
    __table_args__=(
        CheckConstraint("mode IN ('off','test','live') AND revision>=1 AND notice_version='first-party.v1'",name='v1_activity_command_value'),
        CheckConstraint("request_hash ~ '^[a-f0-9]{64}$'",name='v1_activity_command_hash'),
        ForeignKeyConstraint(['business_id','actor_user_id'],['memberships.business_id','memberships.user_id'],name='v1_activity_command_actor_tenant'),
        UniqueConstraint('business_id','revision',name='v1_activity_policy_revision'),
        Index('v1_activity_policy_history','business_id','created_at'),
    )


class ActivityContext(Base):
    __tablename__='v1_activity_contexts'
    id=Column(UUID(as_uuid=True),primary_key=True,default=uuid4)
    business_id=Column(UUID(as_uuid=True),ForeignKey('businesses.id'),nullable=False)
    idempotency_key=Column(UUID(as_uuid=True),nullable=False)
    classification=Column(String(8),nullable=False)
    reason=Column(String(32),nullable=False)
    policy_revision=Column(Integer,nullable=False)
    started_at=Column(DateTime(timezone=True),nullable=False,server_default=func.clock_timestamp())
    expires_at=Column(DateTime(timezone=True),nullable=False)
    retained_until=Column(DateTime(timezone=True),nullable=False)
    lossy=Column(Boolean,nullable=False,server_default='false')
    __table_args__=(
        UniqueConstraint('business_id','id',name='v1_activity_context_tenant'),
        UniqueConstraint('business_id','idempotency_key',name='v1_activity_context_once'),
        CheckConstraint(CLASSIFICATION,name='v1_activity_context_class'),
        ForeignKeyConstraint(['business_id','policy_revision'],['v1_activity_policy_commands.business_id','v1_activity_policy_commands.revision'],name='v1_activity_context_policy'),
        CheckConstraint("(classification='live' AND reason='live_policy') OR (classification='test' AND reason IN ('policy_test','native_context','nonproduction')) OR (classification='unknown' AND reason='unproven')",name='v1_activity_context_class_reason'),
        CheckConstraint("reason IN ('live_policy','policy_test','native_context','nonproduction','unproven') AND policy_revision>=1",name='v1_activity_context_reason'),
        CheckConstraint("expires_at=started_at+interval '30 minutes' AND retained_until=started_at+interval '2160 hours'",name='v1_activity_context_window'),
        Index('v1_activity_context_cohort','business_id','classification','started_at'),
        Index('v1_activity_context_retention','retained_until'),
    )


class ActivityEvent(Base):
    __tablename__='v1_activity_events'
    id=Column(UUID(as_uuid=True),primary_key=True,default=uuid4)
    business_id=Column(UUID(as_uuid=True),nullable=False)
    context_id=Column(UUID(as_uuid=True),nullable=False)
    event_kind=Column(String(24),nullable=False)
    product_id=Column(UUID(as_uuid=True),nullable=True)
    created_at=Column(DateTime(timezone=True),nullable=False,server_default=func.clock_timestamp())
    __table_args__=(
        ForeignKeyConstraint(['business_id','context_id'],['v1_activity_contexts.business_id','v1_activity_contexts.id'],ondelete='CASCADE',name='v1_activity_event_context'),
        ForeignKeyConstraint(['business_id','product_id'],['products.seller_id','products.id'],name='v1_activity_event_product'),
        CheckConstraint("(event_kind='product_view' AND product_id IS NOT NULL) OR (event_kind='checkout_opened' AND product_id IS NULL)",name='v1_activity_event_shape'),
        UniqueConstraint('context_id','event_kind','product_id',postgresql_nulls_not_distinct=True,name='v1_activity_event_once'),
        Index('v1_activity_event_read','business_id','context_id'),
    )


class ActivityGap(Base):
    __tablename__='v1_activity_gaps'
    business_id=Column(UUID(as_uuid=True),ForeignKey('businesses.id'),primary_key=True)
    classification=Column(String(8),primary_key=True)
    minute=Column(DateTime(timezone=True),primary_key=True)
    reason=Column(String(24),primary_key=True)
    __table_args__=(
        CheckConstraint(CLASSIFICATION,name='v1_activity_gap_class'),
        CheckConstraint("reason IN ('context_capacity','event_capacity') AND date_trunc('minute',minute)=minute",name='v1_activity_gap_reason'),
        Index('v1_activity_gap_retention','minute'),
    )


class OrderActivity(Base):
    """Lifetime immutable classification/link, surviving raw event deletion."""
    __tablename__='v1_order_activity'
    order_id=Column(UUID(as_uuid=True),primary_key=True)
    business_id=Column(UUID(as_uuid=True),nullable=False)
    classification=Column(String(8),nullable=False)
    reason=Column(String(32),nullable=False)
    # A checked-at-insert immutable provenance reference, deliberately not a
    # cascading raw-context FK: 90-day cleanup cannot erase order provenance.
    context_id=Column(UUID(as_uuid=True),nullable=True)
    accepted_at=Column(DateTime(timezone=True),nullable=False)
    __table_args__=(
        ForeignKeyConstraint(['business_id','order_id'],['commerce_orders.seller_id','commerce_orders.id'],name='v1_activity_order_tenant'),
        CheckConstraint(CLASSIFICATION,name='v1_activity_order_class'),
        CheckConstraint("reason IN ('live_context','test_context','nonproduction','gateway_test','unproven_context','tracking_disabled')",name='v1_activity_order_reason'),
        CheckConstraint("(classification='live' AND reason='live_context') OR (classification='test' AND reason IN ('test_context','nonproduction','gateway_test')) OR (classification='unknown' AND reason IN ('unproven_context','tracking_disabled'))",name='v1_activity_order_class_reason'),
        CheckConstraint("(reason IN ('live_context','test_context'))=(context_id IS NOT NULL)",name='v1_activity_order_live_link'),
        Index('v1_activity_order_cohort','business_id','classification','accepted_at'),
        Index('v1_activity_order_context','business_id','context_id'),
    )


class ActivitySource(Base):
    """Future server-tagged operational rows; no payload/provider/customer IDs."""
    __tablename__='v1_activity_sources'
    business_id=Column(UUID(as_uuid=True),ForeignKey('businesses.id'),primary_key=True)
    source_kind=Column(String(24),primary_key=True)
    source_id=Column(UUID(as_uuid=True),primary_key=True)
    classification=Column(String(8),nullable=False)
    origin=Column(String(16),nullable=False)
    created_at=Column(DateTime(timezone=True),nullable=False,server_default=func.clock_timestamp())
    retained_until=Column(DateTime(timezone=True),nullable=False)
    __table_args__=(
        CheckConstraint(CLASSIFICATION,name='v1_activity_source_class'),
        CheckConstraint("source_kind IN ('instagram_ingress','wa_inbound','wa_outbound','comment_action') AND origin IN ('inbound','automated','operator','unknown')",name='v1_activity_source_kind'),
        CheckConstraint("retained_until=created_at+interval '2160 hours'",name='v1_activity_source_retention'),
        CheckConstraint("(source_kind IN ('instagram_ingress','wa_inbound') AND origin IN ('inbound','unknown')) OR (source_kind IN ('wa_outbound','comment_action') AND origin IN ('automated','operator','unknown'))",name='v1_activity_source_origin'),
        CheckConstraint("origin<>'unknown' OR classification='unknown'",name='v1_activity_source_unknown'),
        Index('v1_activity_source_cohort','business_id','classification','created_at'),
        Index('v1_activity_source_expiry','retained_until'),
    )
