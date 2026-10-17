"""Operational catalogue.v2 and SKU checkout contracts; preview v1 stays frozen."""
from typing import Literal
from uuid import UUID
from pydantic import Field, field_validator
from app.schemas.catalogue_v1 import Contract, SKURead, SKUWrite, CatalogueReviewWrite
from app.services.commerce import CustomerInput, AddressInput


class ExplicitReview(Contract):
    seller_reviewed: Literal[True]

    @field_validator("seller_reviewed", mode="before")
    @classmethod
    def explicit(cls, value):
        if value is not True:
            raise ValueError("Explicit seller review required")
        return value


class ProductCreate(ExplicitReview):
    idempotency_key: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    category_id: UUID | None = None
    photo_urls: list[str] = Field(default_factory=list, max_length=30)
    skus: list[SKUWrite] = Field(min_length=1, max_length=500)


class ActivationWrite(ExplicitReview):
    expected_mapping_revision: int = Field(strict=True, ge=1)
    expected_legacy_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class OperationalSKUWrite(ExplicitReview):
    expected_mapping_revision: int = Field(strict=True, ge=1)
    skus: list[SKUWrite] = Field(min_length=1, max_length=500)


class ProductMetadataWrite(ExplicitReview):
    expected_mapping_revision: int = Field(strict=True, ge=1)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    category_id: UUID | None = None
    photo_urls: list[str] = Field(default_factory=list, max_length=30)
    active: bool | None = Field(default=None, strict=True)


class StorePolicyWrite(Contract):
    checkout_enabled: bool = Field(strict=True)


class ProductRead(Contract):
    contract_version: Literal["catalogue.v2"] = "catalogue.v2"
    mode: Literal["operational"] = "operational"
    business_id: UUID
    product_id: UUID
    name: str
    description: str
    category_id: UUID | None
    photo_urls: list[str]
    readiness: Literal["active"] = "active"
    checkout_enabled: bool
    skus: list[SKURead]


class CheckoutItem(Contract):
    sku_id: UUID
    quantity: int = Field(strict=True, ge=1, le=20)


class CheckoutWrite(Contract):
    idempotency_key: UUID
    customer: CustomerInput
    address: AddressInput
    items: list[CheckoutItem] = Field(min_length=1, max_length=50)
    note: str = Field(default="", max_length=2000)
    payment_method: Literal["cod", "razorpay"] = "cod"
    whatsapp_updates_opt_in: bool = Field(default=False, strict=True)


class PaymentReconcileWrite(Contract):
    gateway_order_id: str = Field(pattern=r"^order_[A-Za-z0-9]+$", max_length=100)


PUBLIC_PRODUCT_FIELDS = frozenset(ProductRead.model_fields)
