from uuid import uuid4
from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("sellers.id"), nullable=False)
    customer_instagram_id = Column(String, nullable=False)
    customer_name = Column(String, nullable=True)
    customer_gender = Column(String, nullable=True)  # male | female | unknown
    status = Column(String, nullable=False, default="active")  # active | closed
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=True)
    messages = Column(JSONB, default=list)            # [{role, content, timestamp}]
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    seller = relationship("Seller", back_populates="conversations")
    product = relationship("Product", back_populates="conversations")
    orders = relationship("Order", back_populates="conversation")
    product_states = relationship("ConversationProduct", back_populates="conversation")
    alerts = relationship("SellerAlert", back_populates="conversation")
