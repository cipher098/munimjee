"""Strict auth/profile inputs; tenant and inviter identity never come from payloads."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(Input):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def bounded_password(cls, value):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes")
        return value


class SignupInput(LoginInput):
    business_name: str = Field(min_length=2, max_length=160)

    @field_validator("business_name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if len(value) < 2 or any(ord(char) < 32 for char in value):
            raise ValueError("Enter a business name")
        return value


class ProfileInput(Input):
    expected_version: int = Field(strict=True, ge=0)
    name: str = Field(min_length=2, max_length=160)
    business_type: Literal["boutique"]
    country: Literal["IN"]
    support_email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    website: str | None = Field(default=None, max_length=2048)

    @field_validator("name", "phone")
    @classmethod
    def clean_text(cls, value, info):
        if value is None:
            return None
        value = value.strip()
        if any(ord(char) < 32 for char in value):
            raise ValueError("Control characters are not allowed")
        if not value or (info.field_name == "name" and len(value) < 2):
            raise ValueError("Enter a value or leave it blank")
        return value

    @field_validator("website")
    @classmethod
    def public_reference(cls, value):
        if not value:
            return None
        from app.v1.imports.contracts import normalize_url
        return normalize_url(value)


class InvitationInput(Input):
    email: EmailStr
    role: Literal["manager", "staff", "viewer"]


class InvitationAcceptInput(LoginInput):
    token: str = Field(min_length=32, max_length=200)


class MembershipChangeInput(Input):
    # Only explicit revocation is supported here. Owner transfer is a separate flow.
    action: Literal["revoke"]
