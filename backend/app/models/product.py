from uuid import uuid4
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("sellers.id"), nullable=False)
    category_id = Column(UUID(as_uuid=True), ForeignKey("product_categories.id"), nullable=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    listed_price = Column(Integer, nullable=False)   # in paise
    floor_price = Column(Integer, nullable=False)    # private minimum — never exposed to customer
    photo_url = Column(String, nullable=True)        # S3 URL
    photo_urls = Column(JSONB, nullable=True)        # list of additional photo URLs (beyond primary photo_url)
    reel_urls = Column(JSONB, nullable=True)         # list of Instagram reel URLs linked to this product
    warranty_months = Column(Integer, nullable=True)  # None = no warranty
    stock_quantity = Column(Integer, nullable=True)    # None = untracked
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    seller = relationship("Seller", back_populates="products")
    category = relationship("ProductCategory", back_populates="products")
    conversations = relationship("Conversation", back_populates="product")
    orders = relationship("Order", back_populates="product")
    tag_values = relationship("ProductTagValue", back_populates="product", cascade="all, delete-orphan")
    alerts = relationship("SellerAlert", back_populates="product")
