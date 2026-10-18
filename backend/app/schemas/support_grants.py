"""Explicit narrow consent and redacted support projections."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class RecipientLookup(Strict):
    email: EmailStr


class GrantCreate(Strict):
    idempotency_key: UUID
    subject_user_id: UUID
    scope: Literal['readiness.summary']
    reason: str = Field(min_length=1,max_length=200)
    expires_at: datetime
    consented: Literal[True]

    @field_validator('consented',mode='before')
    @classmethod
    def explicit_consent(cls,value):
        if value is not True:raise ValueError('Explicit boolean consent is required')
        return value

    @field_validator('reason')
    @classmethod
    def reason_text(cls,value):
        value=value.strip()
        if not value:raise ValueError('Enter an activity reason')
        return value

    @field_validator('expires_at')
    @classmethod
    def aware(cls,value):
        if value.tzinfo is None:raise ValueError('UTC expiry is required')
        return value


class GrantAction(Strict):
    idempotency_key: UUID
    confirmed: Literal[True]


    @field_validator('confirmed',mode='before')
    @classmethod
    def explicit_confirmation(cls,value):
        if value is not True:raise ValueError('Explicit boolean confirmation is required')
        return value


class GrantRead(Strict):
    grant_id: UUID
    business_id: UUID
    subject_user_id: UUID
    scope: Literal['readiness.summary']
    reason: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime|None
    consented_by_user_id: UUID
    subject_label: str|None=None
    subject_email: str|None=None


class GrantCommandRead(Strict):
    contract_version: Literal['support-command.v1']='support-command.v1'
    business_id: UUID
    grant_id: UUID
    idempotency_key: UUID
    operation: Literal['create','revoke']
    grant: GrantRead
    replayed: bool=False


class SummaryRead(Strict):
    contract_version: Literal['support-summary.v1']='support-summary.v1'
    business_id: UUID
    grant_id: UUID
    idempotency_key: UUID
    scope: Literal['readiness.summary']='readiness.summary'
    name: str
    captured_at: datetime
    expires_at: datetime
    profile_confirmed: bool
    imports_pending: int
    imports_need_review: int
    activated_products: int
    active_skus: int
    store_published: bool
    checkout_policy_enabled: bool
    channel_checks: list[dict]
    provider_approval: Literal['not_evaluated']='not_evaluated'
    onboarding_complete: Literal[False]=False
    replayed: bool=False
