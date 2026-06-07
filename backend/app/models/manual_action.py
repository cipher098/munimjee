from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database import Base


class ManualAction(Base):
    """A post-payment change request (refund / cancellation / item-change) that the bot must
    NOT handle automatically. While an `open` ManualAction exists for a conversation the bot
    stays silent on that chat; the seller reviews it in the dashboard and marks it resolved,
    which un-mutes the bot."""

    __tablename__ = "manual_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("sellers.id"), nullable=False)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    kind = Column(String, nullable=False)            # refund | cancellation | item_change | other
    detail = Column(String, nullable=True)           # the customer's triggering message
    status = Column(String, nullable=False, default="open")  # open | resolved
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)
