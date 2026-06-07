from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class PaymentMethod(Base):
    """A seller's payment destination the bot can share with customers.

    Only `category="upi"` is used today (upi_id + account/payee name + QR image),
    with exactly one row marked `is_primary` per (seller, category) — that's the
    one the bot sends when asking for payment and the one a screenshot is matched
    against. The model is intentionally extensible: future work adds more handles
    per seller and daily/weekly/monthly txn-amount limits + non-UPI categories.
    """

    __tablename__ = "payment_methods"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("sellers.id"), nullable=False, index=True)

    category = Column(String, nullable=False, default="upi")  # "upi" (only one for now)
    upi_id = Column(String, nullable=True)                    # e.g. "shop@okaxis"
    account_name = Column(String, nullable=True)              # payee name as shown in UPI apps
    qr_code_url = Column(String, nullable=True)               # /uploads/... served via PUBLIC_BASE_URL
    label = Column(String, nullable=True)                     # optional seller-facing label

    is_primary = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    seller = relationship("Seller")
