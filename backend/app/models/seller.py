from uuid import uuid4
from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Seller(Base):
    __tablename__ = "sellers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # Instagram fields are nullable: seller signs up first, connects Instagram via OAuth later.
    instagram_id = Column(String, unique=True, nullable=True)
    instagram_token = Column(String, nullable=True)
    instagram_page_id = Column(String, nullable=True)  # IG user ID used to call the messages API
    fb_page_id = Column(String, nullable=True)  # Facebook page ID sent in webhook recipient.id
    instagram_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    whatsapp_number = Column(String, nullable=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    business_name = Column(String, nullable=True)
    # signed_up → instagram_connected → active. Tells the wizard / dashboard which step is next.
    onboarding_state = Column(String, nullable=False, default="signed_up")
    persona = Column(JSONB, nullable=True)
    policies = Column(JSONB, nullable=True)  # {cod: bool, return_days: int|null, delivery_days: str|null}
    # Approved alternative channels the bot is allowed to suggest when the
    # customer asks to move off Instagram. Shape:
    #   [{type: "whatsapp"|"phone"|"email", value: "<contact>"}, ...]
    # Empty/null = bot must keep the conversation on Instagram.
    channels = Column(JSONB, nullable=True)
    negotiation_style = Column(String, default="medium")  # soft | medium | firm
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    products = relationship("Product", back_populates="seller")
    conversations = relationship("Conversation", back_populates="seller")
    orders = relationship("Order", back_populates="seller")
    delivery_members = relationship("DeliveryMember", back_populates="seller")
    product_categories = relationship("ProductCategory", back_populates="seller")
    alerts = relationship("SellerAlert", back_populates="seller")
