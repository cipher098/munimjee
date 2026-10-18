"""Allowlisted design settings; no HTML, CSS, arbitrary asset or link inputs."""
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


class ThemeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    theme: Literal["editorial", "catalogue", "video"] = "catalogue"
    palette: Literal["rose", "forest", "indigo"] = "forest"
    brand_tagline: str = Field(default="", max_length=80, strict=True)
    hero_eyebrow: str = Field(default="", max_length=60, strict=True)
    hero_headline: str = Field(default="", max_length=100, strict=True)
    hero_intro: str = Field(default="", max_length=300, strict=True)
    collection_heading: str = Field(default="", max_length=100, strict=True)
    story_heading: str = Field(default="", max_length=100, strict=True)
    story_body: str = Field(default="", max_length=1000, strict=True)
    show_story: StrictBool = True
    show_categories: StrictBool = True

    @field_validator("brand_tagline", "hero_eyebrow", "hero_headline", "hero_intro", "collection_heading", "story_heading", "story_body")
    @classmethod
    def plain_text(cls, value):
        if re.search(r"[<>\x00-\x08\x0b-\x1f\x7f]", value):
            raise ValueError("Use plain text without markup or control characters")
        return value.strip()


class ThemeDraftWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0, le=2_000_000_000, strict=True)
    idempotency_key: UUID
    config: ThemeConfig


class ThemePublishWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1, le=2_000_000_000, strict=True)
    idempotency_key: UUID
