"""Draft/published design and durable command receipts. DDL reserved by integrator."""
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from app.database import Base


class StorefrontThemeSettings(Base):
    __tablename__ = "storefront_theme_settings_v1"
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True)
    version = Column(Integer, nullable=False)
    draft_config = Column(JSONB, nullable=False)
    published_config = Column(JSONB, nullable=True)
    published_revision = Column(Integer, nullable=False, default=0, server_default="0")
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    published_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        CheckConstraint("version >= 1 AND published_revision >= 0 AND published_revision <= version", name="theme_settings_versions"),
        CheckConstraint("(published_config IS NULL AND published_revision = 0 AND published_at IS NULL) OR (published_config IS NOT NULL AND published_revision > 0 AND published_at IS NOT NULL)", name="theme_settings_publication"),
    )


class StorefrontThemeCommand(Base):
    __tablename__ = "storefront_theme_commands_v1"
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True)
    idempotency_key = Column(UUID(as_uuid=True), primary_key=True)
    operation = Column(String(16), nullable=False)
    request_hash = Column(String(64), nullable=False)
    result = Column(JSONB, nullable=False)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (CheckConstraint("operation IN ('save','publish')", name="theme_command_operation"),)
