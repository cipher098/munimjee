"""Native operator commands, never authorization or send assertions."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: UUID


class RuleFacts(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    enabled: StrictBool = False
    media_id: str = Field(pattern=r'^\d{1,100}$')
    keywords: list[str] = Field(min_length=1, max_length=30)
    product_id: UUID
    private_reply: str = Field(min_length=1, max_length=700)
    public_reply: str | None = Field(default=None, max_length=500)

    @field_validator('keywords')
    @classmethod
    def keywords_clean(cls, values):
        if any(not value.strip() or len(value) > 60 or '\x00' in value for value in values):
            raise ValueError('Use nonempty keywords of at most 60 characters')
        for value in values:
            value.encode('utf-8')
        return values

    @field_validator('name', 'private_reply', 'public_reply')
    @classmethod
    def text_clean(cls, value):
        if value is None:
            return value
        if not value.strip() or '\x00' in value:
            raise ValueError('Use nonempty text without NUL characters')
        value.encode('utf-8')
        return value


class RuleSave(Command):
    facts: RuleFacts
    expected_fingerprint: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class RuleDisable(Command):
    expected_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')


class ReviewClose(Command):
    confirmed: Literal[True]
    reason: str = Field(min_length=10, max_length=1000)
    expected_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')

    @field_validator('confirmed', mode='before')
    @classmethod
    def explicitly_confirmed(cls, value):
        if value is not True:
            raise ValueError('Explicit confirmation is required')
        return value

    @field_validator('reason')
    @classmethod
    def reason_clean(cls, value):
        if len(value.strip()) < 10 or '\x00' in value:
            raise ValueError('Explain the review in at least ten characters')
        value.encode('utf-8')
        return value


class Preview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    rule_id: UUID
    text: str = Field(max_length=10000)
    media_id: str = Field(pattern=r'^\d{1,100}$')

    @field_validator('text')
    @classmethod
    def encodable(cls, value):
        if '\x00' in value:
            raise ValueError('NUL characters are unavailable')
        value.encode('utf-8')
        return value
