"""Strict normal-membership assistance contracts; no support grant or credentials."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class AssignmentWrite(Contract):
    idempotency_key: UUID
    expected_version: StrictInt = Field(ge=0, le=2000000000)
    assignee_user_id: UUID | None
    reviewed: StrictBool

    @field_validator('reviewed')
    @classmethod
    def confirmed(cls,value):
        if value is not True:raise ValueError('Review the assignment before saving')
        return value


class AssistanceOpenWrite(Contract):
    idempotency_key: UUID


class AssignmentRead(Contract):
    version: int = Field(ge=0)
    assignee_user_id: UUID | None
    display_name: str | None
    eligible: bool
    updated_at: datetime | None


class AssistanceStep(Contract):
    id: str
    label: str
    status: Literal['ready_local','action_required','pending_external']
    reason: str
    action_url: str | None


class ChannelCheck(Contract):
    channel: Literal['instagram','whatsapp']
    checked_at: datetime | None
    status: str
    verification_scope: Literal['local_account_access'] = 'local_account_access'
    provider_approval: Literal['not_evaluated'] = 'not_evaluated'


class AssistanceBusinessRead(Contract):
    contract_version: Literal['assistance-business.v1'] = 'assistance-business.v1'
    business_id: UUID
    name: str
    role: Literal['owner','manager','staff','viewer']
    can_assign: bool
    assignment: AssignmentRead
    steps: list[AssistanceStep]
    channel_checks: list[ChannelCheck]
    onboarding_complete: Literal[False] = False


class AssistancePage(Contract):
    contract_version: Literal['assistance-page.v1'] = 'assistance-page.v1'
    items: list[AssistanceBusinessRead]
    next_after: UUID | None


class AssistanceCommandRead(Contract):
    contract_version: Literal['assistance-command.v1'] = 'assistance-command.v1'
    business_id: UUID
    idempotency_key: UUID
    operation: Literal['assignment','open']
    version: int | None
    assignee_user_id: UUID | None
    workspace_url: str
    replayed: StrictBool
