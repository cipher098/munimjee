"""Frozen catalogue.v1 preview contracts; tenant identity comes from auth context."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


MinorUnits = Annotated[int, Field(strict=True, ge=0, le=2_000_000_000)]
AvailableUnits = Annotated[int, Field(strict=True, ge=0, le=2_000_000_000)]
# This slice preserves the existing checkout currency. More currencies require
# explicit B30 contract expansion; a currency code never implies conversion.
Currency = Literal["INR"]
Readiness = Literal["needs_review", "default_backfilled", "reviewed", "stale"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SKUFields(Contract):
    options: dict[str, str] = Field(default_factory=dict)
    price_minor: MinorUnits
    currency: Currency
    stock_available: AvailableUnits | None
    active: bool = Field(strict=True)

    @field_validator("options")
    @classmethod
    def validate_options(cls, value):
        if len(value) > 10:
            raise ValueError("At most 10 option dimensions are supported")
        result = {}
        for name, option in value.items():
            name, option = name.strip(), option.strip()
            if not name or not option or len(name) > 64 or len(option) > 200:
                raise ValueError("Option names and values must be nonempty and bounded")
            if name.casefold() in {key.casefold() for key in result}:
                raise ValueError("Duplicate option dimension")
            result[name] = option
        return result


class SKUWrite(SKUFields):
    sku_id: UUID | None = None
    # Index, rather than label, disambiguates repeated legacy labels.
    legacy_variant_index: Annotated[int, Field(strict=True, ge=0)] | None = None


class CatalogueReviewWrite(Contract):
    """Full seller-reviewed allocation, never raw/unapproved import extraction."""
    expected_legacy_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_mapping_revision: int = Field(strict=True, ge=1)
    seller_reviewed: Literal[True]
    skus: list[SKUWrite] = Field(min_length=1, max_length=500)

    @field_validator("seller_reviewed", mode="before")
    @classmethod
    def require_explicit_review(cls, value):
        if value is not True:
            raise ValueError("Explicit seller review is required")
        return value


class SKURead(SKUFields):
    sku_id: UUID
    product_id: UUID


class CatalogueProductRead(Contract):
    contract_version: Literal["catalogue.v1"] = "catalogue.v1"
    mode: Literal["preview_foundation"] = "preview_foundation"
    business_id: UUID
    product_id: UUID
    name: str
    description: str
    category_id: UUID | None
    photo_urls: list[str]
    readiness: Readiness
    checkout_enabled: Literal[False] = False
    skus: list[SKURead]


class CatalogueMappingRead(Contract):
    """Seller-only reconciliation contract, excluded from public product fields."""
    business_id: UUID
    product_id: UUID
    readiness: Readiness
    mapping_revision: int = Field(strict=True, ge=1)
    legacy_fingerprint: str
    issues: list[str]
    legacy_variants: list[dict]


PUBLIC_PRODUCT_FIELDS = frozenset(CatalogueProductRead.model_fields)
PUBLIC_SKU_FIELDS = frozenset(SKURead.model_fields)
REVIEW_WRITE_FIELDS = frozenset(CatalogueReviewWrite.model_fields)
SKU_WRITE_FIELDS = frozenset(SKUWrite.model_fields)
