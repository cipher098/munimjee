from uuid import uuid4
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
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
    state = Column(String, nullable=False, default="greeting")
    # States: greeting | product_inquiry | negotiating | awaiting_payment
    #         verifying | payment_confirmed | failed | manual_review | dispatched_notified
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=True)
    agreed_price = Column(Integer, nullable=True)      # in paise
    last_counter_price = Column(Integer, nullable=True) # lowest price bot has offered so far (paise)
    negotiation_round = Column(Integer, default=0)
    messages = Column(JSONB, default=list)            # [{role, content, timestamp}]
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    seller = relationship("Seller", back_populates="conversations")
    product = relationship("Product", back_populates="conversations")
    orders = relationship("Order", back_populates="conversation")
