from uuid import uuid4
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("sellers.id"), nullable=False)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    customer_name = Column(String, nullable=False)
    customer_instagram_id = Column(String, nullable=False)
    customer_address = Column(Text, nullable=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    amount = Column(Integer, nullable=False)          # in paise
    status = Column(String, nullable=False, default="payment_confirmed")
    # Statuses: payment_confirmed | delivery_queue | packed | dispatched | delivered
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    seller = relationship("Seller", back_populates="orders")
    conversation = relationship("Conversation", back_populates="orders")
    product = relationship("Product", back_populates="orders")
    delivery_updates = relationship("DeliveryUpdate", back_populates="order")
    transactions = relationship("Transaction", back_populates="order")
    items = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    conversation_product_id = Column(UUID(as_uuid=True), ForeignKey("conversation_products.id"), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Integer, nullable=False)  # paise — agreed price per unit
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="items")
    conversation_product = relationship("ConversationProduct")
