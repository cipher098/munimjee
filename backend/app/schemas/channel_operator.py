from typing import Literal
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Mutation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID


class Review(Mutation):
    decision: Literal["resolve", "replay"]
    reviewed: bool
    reason: str = Field(min_length=10, max_length=500)
    expected_updated_at: datetime

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value):
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Add a review note of at least 10 characters")
        return value


class WhatsAppConnect(Mutation):
    phone_number_id: str = Field(pattern=r"^\d{1,40}$")
    waba_id: str = Field(pattern=r"^\d{1,40}$")
    access_token: str = Field(min_length=10, max_length=4096)


class Automation(Mutation):
    enabled: bool
