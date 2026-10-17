"""Tenant-owned existing-parcel links; carrier tracking never mutates order truth."""
from uuid import uuid4
from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey, ForeignKeyConstraint, UniqueConstraint, Index, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.database import Base

class ParcelConnector(Base):
    __tablename__='v1_parcel_connectors'
    id=Column(UUID(as_uuid=True),primary_key=True,default=uuid4)
    business_id=Column(UUID(as_uuid=True),ForeignKey('businesses.id'),nullable=False,unique=True)
    instance_id=Column(UUID(as_uuid=True),nullable=False,unique=True)
    origin=Column(String(300),nullable=False)
    credential_ref=Column(String(64),nullable=False)
    enabled=Column(Boolean,nullable=False,default=False)
    __table_args__=(UniqueConstraint('business_id','id',name='v1_parcel_connector_tenant'),)

class OrderParcelLink(Base):
    __tablename__='v1_order_parcel_links'
    id=Column(UUID(as_uuid=True),primary_key=True,default=uuid4)
    business_id=Column(UUID(as_uuid=True),nullable=False)
    order_id=Column(UUID(as_uuid=True),nullable=False)
    connector_id=Column(UUID(as_uuid=True),nullable=False)
    actor_id=Column(UUID(as_uuid=True),ForeignKey('users.id'),nullable=False)
    idempotency_key=Column(UUID(as_uuid=True),nullable=False)
    request_hash=Column(String(64),nullable=False)
    order_fingerprint=Column(String(64),nullable=False)
    courier_id=Column(String(40),nullable=False)
    awb=Column(String(35),nullable=False)
    remote_id=Column(UUID(as_uuid=True))
    state=Column(String(32),nullable=False,default='pending_enrollment')
    revision=Column(Integer,nullable=False,default=1)
    lease_token=Column(UUID(as_uuid=True))
    lease_until=Column(DateTime(timezone=True))
    next_poll_at=Column(DateTime(timezone=True),nullable=False,server_default=func.now())
    snapshot_revision=Column(Integer,nullable=False,default=0)
    tracking_state=Column(String(32),nullable=False,default='awaiting_update')
    raw_status=Column(String(120),nullable=False,default='Awaiting update')
    checked_at=Column(DateTime(timezone=True))
    attempted_at=Column(DateTime(timezone=True))
    last_sync_at=Column(DateTime(timezone=True))
    error_code=Column(String(64))
    created_at=Column(DateTime(timezone=True),nullable=False,server_default=func.now())
    __table_args__=(UniqueConstraint('business_id','id',name='v1_parcel_link_tenant'),
        UniqueConstraint('business_id','idempotency_key',name='v1_parcel_command_key'),
        ForeignKeyConstraint(['business_id','order_id'],['commerce_orders.seller_id','commerce_orders.id']),
        ForeignKeyConstraint(['business_id','connector_id'],['v1_parcel_connectors.business_id','v1_parcel_connectors.id']),
        Index('v1_parcel_one_order','business_id','order_id',unique=True,postgresql_where=text("state <> 'unlinked'")),
        Index('v1_parcel_one_awb','connector_id','courier_id','awb',unique=True,postgresql_where=text("state <> 'unlinked'")),
        Index('v1_parcel_one_remote','connector_id','remote_id',unique=True,postgresql_where=text("state <> 'unlinked'")))

class ParcelObservation(Base):
    __tablename__='v1_parcel_observations'
    id=Column(UUID(as_uuid=True),primary_key=True,default=uuid4)
    business_id=Column(UUID(as_uuid=True),nullable=False)
    link_id=Column(UUID(as_uuid=True),nullable=False)
    event_hash=Column(String(64),nullable=False)
    raw_time=Column(String(100),nullable=False,default='')
    event_at=Column(DateTime(timezone=True))
    status=Column(String(120),nullable=False)
    description=Column(String(500),nullable=False,default='')
    location=Column(String(200),nullable=False,default='')
    observed_at=Column(DateTime(timezone=True),nullable=False,server_default=func.now())
    __table_args__=(UniqueConstraint('link_id','event_hash',name='v1_parcel_event_dedupe'),
        ForeignKeyConstraint(['business_id','link_id'],['v1_order_parcel_links.business_id','v1_order_parcel_links.id']))

class ParcelNotification(Base):
    __tablename__='v1_parcel_notifications'
    id=Column(UUID(as_uuid=True),primary_key=True,default=uuid4)
    business_id=Column(UUID(as_uuid=True),nullable=False)
    link_id=Column(UUID(as_uuid=True),nullable=False)
    milestone=Column(String(32),nullable=False)
    decision=Column(String(32),nullable=False)
    reason=Column(String(64),nullable=False)
    outbox_id=Column(UUID(as_uuid=True),ForeignKey('whatsapp_messages.id'))
    created_at=Column(DateTime(timezone=True),nullable=False,server_default=func.now())
    __table_args__=(UniqueConstraint('link_id','milestone',name='v1_parcel_milestone_once'),
        ForeignKeyConstraint(['business_id','link_id'],['v1_order_parcel_links.business_id','v1_order_parcel_links.id']))

class ParcelAudit(Base):
    __tablename__='v1_parcel_audits'
    id=Column(UUID(as_uuid=True),primary_key=True,default=uuid4)
    business_id=Column(UUID(as_uuid=True),nullable=False)
    link_id=Column(UUID(as_uuid=True),nullable=False)
    actor_id=Column(UUID(as_uuid=True),ForeignKey('users.id'),nullable=False)
    action=Column(String(40),nullable=False)
    idempotency_key=Column(UUID(as_uuid=True),nullable=False)
    details=Column(JSONB,nullable=False,default=dict)
    created_at=Column(DateTime(timezone=True),nullable=False,server_default=func.now())
    __table_args__=(UniqueConstraint('business_id','idempotency_key',name='v1_parcel_audit_key'),ForeignKeyConstraint(['business_id','link_id'],['v1_order_parcel_links.business_id','v1_order_parcel_links.id']),)
