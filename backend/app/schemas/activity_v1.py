"""Strict first-party activity allowlists; no client identity/classification claims."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from app.schemas.analytics_v1 import CurrencyTotals


class Contract(BaseModel):
    model_config=ConfigDict(extra='forbid')


Mode=Literal['off','test','live']


class PolicyWrite(Contract):
    expected_revision:int=Field(strict=True,ge=0)
    idempotency_key:UUID
    mode:Mode
    first_party_measurement_acknowledged:bool=Field(strict=True)

    @model_validator(mode='after')
    def notice(self):
        if self.mode!='off' and self.first_party_measurement_acknowledged is not True:
            raise ValueError('Explicit first-party measurement acknowledgement required')
        return self


class PolicyRead(Contract):
    contract_version:Literal['activity-policy.v1']='activity-policy.v1'
    business_id:UUID
    mode:Mode
    revision:int=Field(strict=True,ge=0)
    changed_at:AwareDatetime|None
    can_change:bool=Field(strict=True)
    collector_available:bool=Field(strict=True)
    notice_version:Literal['first-party.v1']='first-party.v1'
    retention_days:Literal[90]=90


class PolicyReceipt(Contract):
    contract_version:Literal['activity-policy-receipt.v1']='activity-policy-receipt.v1'
    business_id:UUID
    idempotency_key:UUID
    mode:Mode
    applied_revision:int=Field(strict=True,ge=1)
    accepted_at:AwareDatetime
    replayed:bool=Field(strict=True)


class ContextWrite(Contract):
    idempotency_key:UUID


class ContextRead(Contract):
    contract_version:Literal['activity-context.v1']='activity-context.v1'
    state:Literal['ready','disabled','excluded','expired','capped']
    context_id:UUID|None=None
    expires_at:AwareDatetime|None=None
    capability:str|None=Field(default=None,max_length=4096)


class EventWrite(Contract):
    event_kind:Literal['product_view','checkout_opened']
    product_id:UUID|None=None

    @model_validator(mode='after')
    def shape(self):
        if (self.event_kind=='product_view')!=(self.product_id is not None):
            raise ValueError('Only product_view requires a product ID')
        return self


class EventRead(Contract):
    contract_version:Literal['activity-event.v1']='activity-event.v1'
    state:Literal['accepted','capped','disabled']
    replayed:bool=Field(strict=True)


class Coverage(Contract):
    state:Literal['disabled','not_started','partial','available']
    measurement_mode:Mode
    available_from:AwareDatetime|None
    available_to:AwareDatetime|None
    reasons:list[Literal['measurement_off','collector_disabled','measurement_not_started','uncovered_interval','retention_truncated','ingestion_capped']]
    retention_days:Literal[90]=90
    retention_ready:bool=Field(strict=True)
    cleanup_overdue_rows:int=Field(strict=True,ge=0)
    cleanup_lag_seconds:int|None=Field(default=None,strict=True,ge=0)


class Counts(Contract):
    visits:int|None=Field(default=None,strict=True,ge=0)
    product_views:int|None=Field(default=None,strict=True,ge=0)
    checkout_starts:int|None=Field(default=None,strict=True,ge=0)
    accepted_placements:int|None=Field(default=None,strict=True,ge=0)


class Conversion(Contract):
    numerator:int|None=Field(default=None,strict=True,ge=0)
    denominator:int|None=Field(default=None,strict=True,ge=0)
    percentage:str|None=Field(default=None,pattern=r'^(100\.00|[0-9]{1,2}\.[0-9]{2})$')
    window_minutes:Literal[30]=30
    unavailable_reason:Literal['measurement_off','collector_disabled','measurement_not_started','partial_coverage','no_observed_contexts']|None

    @model_validator(mode='after')
    def ratio(self):
        if self.numerator is not None and self.denominator is not None and self.numerator>self.denominator:
            raise ValueError('Converted contexts cannot exceed observed contexts')
        if self.percentage is not None and (not self.denominator or self.numerator is None or self.unavailable_reason is not None):
            raise ValueError('Unsupported conversion percentage')
        if self.percentage is None and self.unavailable_reason is None:
            raise ValueError('Unavailable conversion requires its reason')
        if self.percentage is not None:
            expected=(Decimal(self.numerator)*100/Decimal(self.denominator)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
            if self.percentage!=format(expected,'.2f'):
                raise ValueError('Conversion must match its exact numerator and denominator')
        return self


class ProductionOrders(Contract):
    state:Literal['not_started','partial','available']
    placed:int|None=Field(default=None,strict=True,ge=0)
    online_paid:int|None=Field(default=None,strict=True,ge=0)
    cod_collected:int|None=Field(default=None,strict=True,ge=0)
    cancelled:int|None=Field(default=None,strict=True,ge=0)
    expired:int|None=Field(default=None,strict=True,ge=0)
    currency_totals:list[CurrencyTotals]
    excluded_test:int=Field(strict=True,ge=0)
    excluded_unclassified:int=Field(strict=True,ge=0)


class AutomationOutcomes(Contract):
    queued:int=Field(strict=True,ge=0)
    sending:int=Field(strict=True,ge=0)
    accepted:int=Field(strict=True,ge=0)
    failed:int=Field(strict=True,ge=0)
    unknown:int=Field(strict=True,ge=0)
    # No future IG send or successful resolution claim can appear accidentally.
    instagram_sends:None=None
    resolved_enquiries:None=None


class ChannelActivity(Contract):
    enquiry_messages:int|None=Field(default=None,strict=True,ge=0)
    automation_outcomes:AutomationOutcomes|None=None
    included_source_kinds:list[Literal['instagram_ingress','wa_inbound','wa_outbound','comment_action']]=Field(default_factory=list,max_length=4)
    excluded_test:int=Field(default=0,strict=True,ge=0)
    excluded_unclassified:int=Field(default=0,strict=True,ge=0)
    reason:Literal['producer_not_installed','measurement_not_started','partial_coverage','no_production_observations']|None

    @model_validator(mode='after')
    def partial_observations(self):
        kinds=set(self.included_source_kinds)
        if len(kinds)!=len(self.included_source_kinds):raise ValueError('Source kinds must be unique')
        if self.reason in {'partial_coverage','no_production_observations'}:
            inbound=bool(kinds & {'instagram_ingress','wa_inbound'})
            outbound=bool(kinds & {'wa_outbound','comment_action'})
            if inbound!=(self.enquiry_messages is not None) or (self.enquiry_messages is not None and self.enquiry_messages<1):
                raise ValueError('Only observed inbound families have a count')
            if outbound!=(self.automation_outcomes is not None):raise ValueError('Only observed outbound families have counts')
            if self.automation_outcomes is not None and not sum(getattr(self.automation_outcomes,k) for k in ('queued','sending','accepted','failed','unknown')):
                raise ValueError('An observed outbound family must have an outcome')
            if bool(kinds)!=(self.reason=='partial_coverage'):raise ValueError('Observed coverage remains partial')
        return self


class ActivityRead(Contract):
    contract_version:Literal['seller-activity.v1']='seller-activity.v1'
    business_id:UUID
    from_date:date
    to_date:date
    generated_at:AwareDatetime
    coverage:Coverage
    counts:Counts
    conversion:Conversion
    production_orders:ProductionOrders
    channel_activity:ChannelActivity
    attribution:None=None
