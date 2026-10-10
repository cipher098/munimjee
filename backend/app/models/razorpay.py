"""Seller-owned gateway credentials, encrypted separately from public store data."""

from sqlalchemy import Boolean, Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class RazorpayAccount(Base):
    __tablename__ = "razorpay_accounts"
    seller_id = Column(UUID(as_uuid=True), ForeignKey("sellers.id"), primary_key=True)
    key_id = Column(String(100), nullable=False)
    key_secret = Column(Text, nullable=False)
    webhook_secret = Column(Text, nullable=False)
    mode = Column(String(4), nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
