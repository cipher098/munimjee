"""Seller analytics v1: order-created cohorts, current canonical states, exact minor units."""
from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, AwareDatetime

PaymentStatus = Literal['pending','collected','cancelled','paid','expired','review_required']
FulfillmentStatus = Literal['pending','confirmed','packed','shipped','delivered','cancelled']
PaymentMethod = Literal['cod','razorpay']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Filters(Contract):
    from_date: date
    to_date: date
    payment_status: PaymentStatus | None
    fulfillment_status: FulfillmentStatus | None
    payment_method: PaymentMethod | None
    include_gateway_test: StrictBool
    page: StrictInt = Field(ge=1,le=1000)
    page_size: StrictInt = Field(ge=1,le=50)


class Counts(Contract):
    placed: int = Field(ge=0,strict=True)
    online_paid: int = Field(ge=0,strict=True)
    cod_collected: int = Field(ge=0,strict=True)
    payment_review: int = Field(ge=0,strict=True)
    cancelled: int = Field(ge=0,strict=True)
    expired: int = Field(ge=0,strict=True)
    unclassified_test_activity: int = Field(ge=0,strict=True)


class CurrencyTotals(Contract):
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    placed_order_value_minor: str = Field(pattern=r'^(0|[1-9][0-9]*)$')
    online_paid_minor: str = Field(pattern=r'^(0|[1-9][0-9]*)$')
    cod_collected_minor: str = Field(pattern=r'^(0|[1-9][0-9]*)$')
    captured_review_minor: str = Field(pattern=r'^(0|[1-9][0-9]*)$')


class Daily(Contract):
    date: date
    placed: int = Field(ge=0,strict=True)
    cancelled: int = Field(ge=0,strict=True)


class OrderRow(Contract):
    order_id: UUID
    created_at: AwareDatetime
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    total_minor: str = Field(pattern=r'^(0|[1-9][0-9]*)$')
    payment_method: PaymentMethod
    payment_status: PaymentStatus
    fulfillment_status: FulfillmentStatus
    test_classification: Literal['known_gateway_test','known_gateway_live','unclassified']


class Unavailable(Contract):
    visits: None = None
    product_views: None = None
    enquiries: None = None
    checkout_starts: None = None
    conversion_rate: None = None
    attribution: None = None
    completed_refunds_minor: None = None
    payment_fees_minor: None = None
    net_revenue_minor: None = None
    settlement_period_cashflow: None = None


class AnalyticsRead(Contract):
    contract_version: Literal['seller-analytics.v1'] = 'seller-analytics.v1'
    business_id: UUID
    generated_at: AwareDatetime
    metric_basis: Literal['order_created_utc_current_states'] = 'order_created_utc_current_states'
    data_scope: Literal['commerce_orders_only'] = 'commerce_orders_only'
    filters: Filters
    counts: Counts
    currency_totals: list[CurrencyTotals]
    daily: list[Daily]
    orders: list[OrderRow]
    has_next: StrictBool
    known_gateway_test_excluded: int = Field(ge=0,strict=True)
    unavailable: Unavailable = Field(default_factory=Unavailable)
