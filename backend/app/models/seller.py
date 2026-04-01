from uuid import uuid4
from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Seller(Base):
    __tablename__ = "sellers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    instagram_id = Column(String, unique=True, nullable=False)
    instagram_token = Column(String, nullable=False)
    instagram_page_id = Column(String, nullable=False)  # IG user ID used to call the messages API
    fb_page_id = Column(String, nullable=True)  # Facebook page ID sent in webhook recipient.id
    instagram_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    whatsapp_number = Column(String, nullable=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    persona = Column(JSONB, nullable=True)
    policies = Column(JSONB, nullable=True)  # {cod: bool, return_days: int|null, delivery_days: str|null}
    negotiation_style = Column(String, default="medium")  # soft | medium | firm
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    products = relationship("Product", back_populates="seller")
    conversations = relationship("Conversation", back_populates="seller")
    orders = relationship("Order", back_populates="seller")
    delivery_members = relationship("DeliveryMember", back_populates="seller")
