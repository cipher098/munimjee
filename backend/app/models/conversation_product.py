from uuid import uuid4
from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class ConversationProduct(Base):
    __tablename__ = "conversation_products"
    __table_args__ = (
        UniqueConstraint("conversation_id", "product_id", name="uq_conv_product"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)

    negotiation_round = Column(Integer, default=0)
    last_counter_price = Column(Integer, nullable=True)   # paise — lowest price bot offered
    agreed_price = Column(Integer, nullable=True)         # paise — price customer accepted
    photos_sent_count = Column(Integer, default=0)        # how many photos have been sent to this customer for this product

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    conversation = relationship("Conversation", back_populates="product_states")
    product = relationship("Product")
