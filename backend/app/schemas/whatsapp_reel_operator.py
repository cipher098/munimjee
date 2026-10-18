"""Single-source native commands; no recipient, text or authority assertions."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class LinkCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: UUID
    action: Literal['link_only', 'link_and_resume']
    product_id: UUID
    shortcode: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    expected_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    expected_connection_version: StrictInt = Field(ge=0)
    confirmed: Literal[True]

    @field_validator('confirmed', mode='before')
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError('Explicit confirmation required')
        return value
