from uuid import uuid4
from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class ProductTagValue(Base):
    __tablename__ = "product_tag_values"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    tag_id = Column(UUID(as_uuid=True), ForeignKey("category_tags.id", ondelete="CASCADE"), nullable=False)
    value = Column(String, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    product = relationship("Product", back_populates="tag_values")
    tag = relationship("CategoryTag", back_populates="tag_values")

    __table_args__ = (
        UniqueConstraint("product_id", "tag_id", name="uq_product_tag"),
    )
