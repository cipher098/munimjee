"""Internal public-only observations, never a stock reservation or order intent."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class SKUFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    sku_id: UUID
    options: dict[str, str]
    price_minor: Annotated[StrictInt, Field(ge=0, le=2_000_000_000)]
    currency: Literal["INR"]
    stock_available: Annotated[StrictInt, Field(ge=0, le=2_000_000_000)] | None

    @field_validator("options")
    @classmethod
    def safe_options(cls, value):
        if len(value) > 10 or len({key.casefold() for key in value}) != len(value):
            raise ValueError("Options need review")
        for key, label in value.items():
            if not safe_label(key, 64) or not safe_label(label, 200):
                raise ValueError("Options need review")
        return value


def safe_label(value, limit):
    return isinstance(value, str) and 0 < len(value) <= limit and value == value.strip() and not any(
        ord(char) < 32 or ord(char) == 127 or char in "\u2028\u2029" for char in value)


class ProductFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    business_id: UUID
    product_id: UUID
    product_name: str
    mapping_revision: Annotated[StrictInt, Field(ge=1)]
    observed_at: datetime
    skus: Annotated[tuple[SKUFact, ...], Field(min_length=1, max_length=12)]
    fact_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]

    @field_validator("product_name")
    @classmethod
    def safe_name(cls, value):
        if not safe_label(value, 200):
            raise ValueError("Product name needs review")
        return value
