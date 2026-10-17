"""Proposed D10 draft contracts; these are not catalogue or inventory records."""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def clean_text(value: Any, *, limit: int, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError("expected text")
    if len(value) > limit or any(
        (ord(c) < 32 and c not in "\n\t") or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF
        for c in value
    ):
        raise ValueError("text exceeds limit or contains control characters")
    value = value.strip()
    if not value and not empty:
        raise ValueError("text cannot be empty")
    return value


def normalize_url(value: Any) -> str:
    """Conservative reference normalization, never permission to fetch this URL."""
    original = value
    value = clean_text(value, limit=2048)
    if any(c.isspace() for c in original) or "\\" in value:
        raise ValueError("invalid source URL")
    decoded = unquote(value)
    if any(ord(c) < 32 or ord(c) == 127 for c in decoded) or "\\" in decoded:
        raise ValueError("invalid source URL escapes")
    if re.search(r"%(?![0-9a-fA-F]{2})", value):
        raise ValueError("invalid source URL escapes")
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() != "https" or not parts.hostname:
            raise ValueError("source URL must use HTTPS")
        if parts.username is not None or parts.password is not None or parts.port not in (None, 443):
            raise ValueError("credentials and nonstandard ports are forbidden")
        host = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            labels = host.split(".")
            if (
                len(host) > 253 or len(labels) < 2
                or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
                or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid"))
                or host == "localhost"
                or re.fullmatch(r"[0-9.]+", host)
            ):
                raise ValueError("invalid public source hostname")
        else:
            if not address.is_global:
                raise ValueError("non-public source IP forbidden")
            host = f"[{address.compressed}]" if address.version == 6 else address.compressed
        # Query order, case and paths can carry source identity, so preserve them.
        return urlunsplit(("https", host, parts.path or "/", parts.query, ""))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("invalid source URL") from exc


class SourceKind(str, Enum):
    WEBSITE = "website"
    INSTAGRAM = "instagram"
    UPLOADED_MEDIA = "uploaded_media"
    CSV = "csv"


class SourceReference(Contract):
    kind: SourceKind
    url: str | None = None
    media_id: str | None = None

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, value: Any) -> str | None:
        return None if value is None else normalize_url(value)

    @field_validator("media_id", mode="before")
    @classmethod
    def validate_media_id(cls, value: Any) -> str | None:
        if value is None:
            return None
        value = clean_text(value, limit=200)
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
            raise ValueError("invalid media ID")
        return value

    @model_validator(mode="after")
    def required_reference(self) -> SourceReference:
        if self.kind == SourceKind.WEBSITE and not self.url:
            raise ValueError("website source requires URL")
        if self.kind != SourceKind.WEBSITE and not self.media_id:
            raise ValueError("media and CSV sources require stable media/document ID")
        if self.kind == SourceKind.INSTAGRAM and self.url:
            if urlsplit(self.url).hostname not in ("instagram.com", "www.instagram.com"):
                raise ValueError("Instagram URL must belong to instagram.com")
        return self

    def identity(self) -> str:
        # A mutable presentation URL cannot change a stable media identity.
        reference = self.url if self.kind == SourceKind.WEBSITE else self.media_id
        return f"{self.kind.value}:{reference}"


class Provenance(Contract):
    business_id: UUID  # Initial seam: exactly the existing Seller.id.
    import_job_id: UUID
    captured_at: datetime
    source: SourceReference
    source_product_id: str
    evidence: str = ""

    @field_validator("source_product_id", mode="before")
    @classmethod
    def validate_item(cls, value: Any) -> str:
        return clean_text(value, limit=200)

    @field_validator("evidence", mode="before")
    @classmethod
    def validate_evidence(cls, value: Any) -> str:
        return clean_text(value, limit=8000, empty=True)

    @field_validator("captured_at", mode="before")
    @classmethod
    def capture_input(cls, value: Any) -> Any:
        if not isinstance(value, (str, datetime)):
            raise ValueError("capture time must be a timezone-aware timestamp")
        return value

    @field_validator("captured_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("capture time requires timezone")
        return value


class DraftPrice(Contract):
    amount: Decimal
    currency: str

    @field_validator("amount", mode="before")
    @classmethod
    def decimal_only(cls, value: Any) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
            raise ValueError("amount must be decimal text or integer, never float/bool")
        if isinstance(value, str) and not re.fullmatch(r"[0-9]{1,10}(?:\.[0-9]{1,2})?", value):
            raise ValueError("amount requires fixed decimal notation")
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid price") from exc
        if not result.is_finite() or result <= 0 or result > Decimal("999999999.99"):
            raise ValueError("amount outside supported draft range")
        if result.as_tuple().exponent < -2:
            raise ValueError("draft price supports at most two fractional digits")
        return result

    @field_validator("currency", mode="before")
    @classmethod
    def currency_code(cls, value: Any) -> str:
        # Deliberately bounded pilot list, not a claim of international support.
        if value not in ("INR", "USD", "EUR", "GBP", "AED"):
            raise ValueError("unsupported draft currency")
        return value


class DraftOption(Contract):
    name: str
    values: tuple[str, ...] = Field(min_length=1, max_length=30)

    @field_validator("name", mode="before")
    @classmethod
    def option_name(cls, value: Any) -> str:
        return clean_text(value, limit=80)

    @field_validator("values", mode="before")
    @classmethod
    def option_values(cls, value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)) or len(value) > 30:
            raise ValueError("expected bounded option values")
        result = tuple(clean_text(item, limit=80) for item in value)
        if len({item.casefold() for item in result}) != len(result):
            raise ValueError("duplicate option values")
        return result


class DraftFacts(Contract):
    title: str | None = None
    description: str | None = None
    price: DraftPrice | None = None
    stock: int | None = None
    options: tuple[DraftOption, ...] | None = Field(default=None, max_length=8)

    @field_validator("title", "description", mode="before")
    @classmethod
    def fact_text(cls, value: Any, info: Any) -> str | None:
        return None if value is None else clean_text(value, limit=200 if info.field_name == "title" else 4000)

    @field_validator("stock", mode="before")
    @classmethod
    def stock_integer(cls, value: Any) -> int | None:
        if value is not None and (type(value) is not int or not 0 <= value <= 1_000_000):
            raise ValueError("stock must be an explicit bounded nonnegative integer")
        return value

    @field_validator("options", mode="before")
    @classmethod
    def option_list(cls, value: Any) -> Any:
        if value is not None and (not isinstance(value, (list, tuple)) or len(value) > 8):
            raise ValueError("expected bounded options list")
        return value

    @model_validator(mode="after")
    def distinct_options(self) -> DraftFacts:
        if self.options is not None and len({o.name.casefold() for o in self.options}) != len(self.options):
            raise ValueError("duplicate option names")
        return self


class FactField(str, Enum):
    TITLE = "title"
    DESCRIPTION = "description"
    PRICE = "price"
    STOCK = "stock"
    OPTIONS = "options"


class SellerOverride(Contract):
    field: FactField
    value: Any
    reviewer_id: UUID

    @model_validator(mode="after")
    def typed_value(self) -> SellerOverride:
        facts = DraftFacts.model_validate({self.field.value: self.value})
        object.__setattr__(self, "value", getattr(facts, self.field.value))
        return self


class CandidateState(str, Enum):
    PENDING = "pending"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewDecision(Contract):
    reviewer_id: UUID
    confirmed_fields: tuple[FactField, ...]
    reason: str | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def reason_text(cls, value: Any) -> str | None:
        return None if value is None else clean_text(value, limit=1000)


class CandidateInput(Contract):
    provenance: Provenance
    facts: DraftFacts
    seller_product_ref: str | None = None

    @field_validator("seller_product_ref", mode="before")
    @classmethod
    def product_ref(cls, value: Any) -> str | None:
        return None if value is None else clean_text(value, limit=200)


class ImportCandidate(Contract):
    id: UUID
    provenance: Provenance
    extracted: DraftFacts
    seller_product_ref: str | None = None
    state: CandidateState = CandidateState.PENDING
    overrides: tuple[SellerOverride, ...] = ()
    review: ReviewDecision | None = None

    def effective_facts(self) -> DraftFacts:
        values = self.extracted.model_dump()
        values.update({override.field.value: override.value for override in self.overrides})
        return DraftFacts.model_validate(values)
