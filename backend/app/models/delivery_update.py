from uuid import uuid4
from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class DeliveryUpdate(Base):
    __tablename__ = "delivery_updates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    courier_name = Column(String, nullable=True)   # Delhivery | DTDC | India Post | BlueDart | Other
    tracking_id = Column(String, nullable=True)
    image_url = Column(String, nullable=True)      # S3 URL of parcel photo
    message = Column(Text, nullable=True)          # custom message to send to customer
    dispatched_at = Column(DateTime(timezone=True), server_default=func.now())
    notified_at = Column(DateTime(timezone=True), nullable=True)  # set when bot sends customer DM
    created_by = Column(UUID(as_uuid=True), ForeignKey("delivery_members.id"), nullable=False)

    order = relationship("Order", back_populates="delivery_updates")
    created_by_member = relationship("DeliveryMember", back_populates="delivery_updates")
