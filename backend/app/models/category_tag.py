from uuid import uuid4
from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class CategoryTag(Base):
    __tablename__ = "category_tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    category_id = Column(UUID(as_uuid=True), ForeignKey("product_categories.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)           # slug e.g. "power_source"
    display_name = Column(String, nullable=False)   # human label e.g. "Power Source"
    value_type = Column(String, nullable=False, default="text")  # enum | text | number
    allowed_values = Column(JSONB, nullable=True)   # ["AC Power", "Battery"] for enum type
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    category = relationship("ProductCategory", back_populates="tags")
    tag_values = relationship("ProductTagValue", back_populates="tag", cascade="all, delete-orphan")
    waiting_conversations = relationship("Conversation", back_populates="pending_tag")
    alerts = relationship("SellerAlert", back_populates="tag")
