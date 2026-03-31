from uuid import uuid4
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("sellers.id"), nullable=False)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    utr_number = Column(String, unique=True, nullable=False)  # UNIQUE INDEX — fraud prevention
    amount = Column(Integer, nullable=False)         # in paise
    sender_name = Column(String, nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    verified_by = Column(String, nullable=False)     # ocr | sms | statement | manual
    screenshot_url = Column(String, nullable=True)   # S3 URL of original screenshot
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="transactions")
