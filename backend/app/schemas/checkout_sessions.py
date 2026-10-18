"""Frozen public payment handoff/state DTOs. No secret credential is public."""
import re
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import Field, field_validator, model_validator
from app.schemas.catalogue_v1 import Contract, MinorUnits


class PaymentPrefill(Contract):
    name: str = Field(max_length=100)
    contact: str = Field(max_length=20)
    email: str = Field(max_length=254)


class CheckoutSessionRead(Contract):
    contract_version: Literal["checkout-session.v1"] = "checkout-session.v1"
    order_id: UUID
    provider: Literal["razorpay"] = "razorpay"
    provider_order_id: str = Field(pattern=r"^order_[A-Za-z0-9]+$", max_length=100)
    key_id: str = Field(pattern=r"^rzp_(test|live)_[A-Za-z0-9]+$", max_length=100)
    mode: Literal["test", "live"]
    amount_minor: MinorUnits
    currency: Literal["INR"]
    session_token: str = Field(pattern=r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$", max_length=4096)
    expires_at: datetime
    merchant_name: str = Field(min_length=1, max_length=100)
    prefill: PaymentPrefill
    verify_url: str = Field(max_length=512)
    status_url: str = Field(max_length=512)
    order_status_url: str = Field(max_length=512)

    @field_validator("expires_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("Timezone is required")
        return value

    @model_validator(mode="after")
    def exact_public_options(self):
        if self.amount_minor < 100 or not self.key_id.startswith("rzp_" + self.mode + "_"):
            raise ValueError("Invalid payment handoff amount or key mode")
        expected = self.status_url + "/verify"
        if (re.fullmatch(r"/api/v1/storefronts/[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?/orders/" + str(self.order_id) + r"/checkout-session", self.status_url) is None
                or self.verify_url != expected or self.order_status_url != self.status_url.removesuffix("/checkout-session")
                or any(c in self.status_url for c in ("?", "#", "\\"))):
            raise ValueError("Payment paths must match the same order")
        return self


class CheckoutStateRead(Contract):
    contract_version: Literal["checkout-state.v1"] = "checkout-state.v1"
    order_id: UUID
    amount_minor: MinorUnits
    currency: Literal["INR"]
    payment_status: Literal["pending", "paid", "collected", "review_required", "cancelled", "expired"]
    fulfillment_status: Literal["pending", "confirmed", "packed", "shipped", "delivered", "cancelled"]
    attempt_state: Literal["not_started", "requesting", "unknown", "ready"]
    expires_at: datetime | None
    retry_allowed: bool = Field(strict=True)


PUBLIC_SESSION_FIELDS = frozenset(CheckoutSessionRead.model_fields)
PUBLIC_STATE_FIELDS = frozenset(CheckoutStateRead.model_fields)


class PaymentReviewRead(Contract):
    """Native operator facts; never customer capability or gateway credentials."""
    contract_version: Literal["payment-review.v1"] = "payment-review.v1"
    order_id: UUID
    attempt_state: Literal["not_started", "requesting", "unknown", "ready"]
    gateway_order_id: str | None = Field(default=None, pattern=r"^order_[A-Za-z0-9]+$", max_length=100)
    payment_status: Literal["pending", "paid", "collected", "review_required", "cancelled", "expired"]
    fulfillment_status: Literal["pending", "confirmed", "packed", "shipped", "delivered", "cancelled"]
    reconciliation_eligible: bool = Field(strict=True)


class GatewayConfigurationRead(Contract):
    configured: bool = Field(strict=True)
    enabled: bool = Field(strict=True)
    mode: Literal["test", "live"]
    key_id: str = Field(max_length=100)
    webhook_url: str = Field(max_length=4096)
    encryption_ready: bool = Field(strict=True)
    configuration_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    connection_verification: Literal["not_performed"] = "not_performed"
