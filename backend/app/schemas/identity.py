"""Public V1 identity responses deliberately exclude legacy seller secrets."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel


class BusinessView(BaseModel):
    id: UUID
    name: str
    role: Literal["owner", "manager", "staff", "viewer"]
    capabilities: list[str]


class MeView(BaseModel):
    user_id: UUID
    auth_method: Literal["legacy_owner", "v1_user"]
    businesses: list[BusinessView]


class ReadinessCheck(BaseModel):
    key: str
    status: Literal["ready", "not_evaluated"]


class BusinessReadinessView(BaseModel):
    business_id: UUID
    scope: Literal["identity_foundation"] = "identity_foundation"
    identity_ready: bool
    # None explicitly means this slice has not evaluated full seller onboarding.
    onboarding_complete: bool | None = None
    legacy_onboarding_state: str | None
    checks: list[ReadinessCheck]
