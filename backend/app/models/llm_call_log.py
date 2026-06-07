"""Per-call LLM usage + cost ledger.

One row per LLM API call (decide / generate_reply / intent_classifier /
vision / catalog match / …). Captures the full request and response, token
usage (incl. Anthropic prompt-cache buckets), the resolved provider/model,
and the computed USD cost — so cost-per-conversation can be queried anytime.

`customer_message_mid` is the Instagram message id of the inbound customer
message that triggered the turn, letting cost be attributed down to a single
inbound message (there is no separate Message table — messages live as a
JSONB list on the conversation).
"""
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base


class LLMCallLog(Base):
    __tablename__ = "llm_call_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # --- context (all nullable: admin/training calls have no conversation) ---
    seller_id = Column(UUID(as_uuid=True), ForeignKey("sellers.id"), nullable=True, index=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=True, index=True)
    conversation_product_id = Column(UUID(as_uuid=True), ForeignKey("conversation_products.id"), nullable=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=True)
    customer_message_mid = Column(String, nullable=True, index=True)

    # --- which call + which model ---
    method = Column(String, nullable=False)     # "decide", "generate_reply", "intent_classifier", ...
    provider = Column(String, nullable=False)   # "anthropic" | "sarvam"
    model = Column(String, nullable=False)
    status = Column(String, nullable=False, default="success")  # "success" | "error"

    # --- usage ---
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    cache_read_input_tokens = Column(Integer, nullable=True)
    cache_creation_input_tokens = Column(Integer, nullable=True)

    # --- computed cost (USD). NULL when the model isn't priced in pricing.yaml ---
    cost_usd = Column(Numeric(14, 8), nullable=True)

    # --- full payloads ---
    request = Column(JSONB, nullable=True)   # {model, max_tokens, system, messages} (base64 image data elided)
    response = Column(Text, nullable=True)   # full response text
    error = Column(Text, nullable=True)      # set when status="error"

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
