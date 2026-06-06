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
    # No product_id: an order is a deal of one-or-more products — the products live
    # on its OrderItems (conversation_product_id → ConversationProduct.product_id).
    amount = Column(Integer, nullable=False)          # in paise — total due for this order
    status = Column(String, nullable=False, default="payment_confirmed")
    # Statuses: awaiting_payment | payment_confirmed | delivery_queue | packed | dispatched | delivered
    # Payment facts (moved here from ConversationProduct — the Order is the
    # per-purchase-cycle payment container, created when payment starts):
    amount_paid = Column(Integer, nullable=False, default=0)   # paise — cumulative verified payments
    payment_method_id = Column(UUID(as_uuid=True), ForeignKey("payment_methods.id"), nullable=True)  # method we shared
    payment_requested_at = Column(DateTime(timezone=True), nullable=True)  # when we shared the QR (verify-window start)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    seller = relationship("Seller", back_populates="orders")
    conversation = relationship("Conversation", back_populates="orders")
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
