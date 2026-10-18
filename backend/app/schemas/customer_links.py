from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictBool


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: UUID


class Start(Command):
    conversation_id: UUID
    contact_id: UUID
    scope_confirmed: StrictBool


class Finish(Command):
    expected_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    confirmed: StrictBool


class Unlink(Command):
    expected_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    confirmed: StrictBool
    reason: str = Field(min_length=10, max_length=300)
