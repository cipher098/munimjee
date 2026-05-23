"""Fake versions of the external integration clients for scenario tests.

These satisfy the surface area `responder.py` and `conversation.py` actually
use — `send_message`, `send_image`, and the read-only helpers — without
making real network calls. Each fake records every call so tests can assert
"the bot called send_message with text containing '1100'" without parsing
worker logs.

Why we don't just `Mock(spec=InstagramClient)`:
  - the integrations module init reads `settings` at import time
    (instagram_token, fb_page_id), which trips when the env isn't fully
    populated in tests
  - explicit fakes give us a stable interface to grep for
  - recorded `calls` lists are friendlier than digging through Mock.call_args
"""
from __future__ import annotations

from typing import Any


class FakeInstagramClient:
    """Drop-in replacement for app.integrations.instagram.InstagramClient.

    Records every send_message/send_image call so the scenario harness can
    assert on what the bot tried to send. Returns a synthetic mid so the
    downstream `_tag_last_bot_message_mid` logic still works.
    """

    def __init__(self, token: str | None = None, fb_page_id: str | None = None):
        self.token = token
        self.fb_page_id = fb_page_id
        self.calls: list[dict[str, Any]] = []
        self._mid_counter = 0

    def _next_mid(self) -> str:
        self._mid_counter += 1
        return f"fake-mid-{self._mid_counter}"

    async def send_message(self, recipient_id: str, text: str) -> dict:
        mid = self._next_mid()
        self.calls.append({"type": "send_message", "recipient_id": recipient_id, "text": text, "mid": mid})
        return {"message_id": mid}

    async def send_image(self, recipient_id: str, image_url: str) -> dict:
        mid = self._next_mid()
        self.calls.append({"type": "send_image", "recipient_id": recipient_id, "image_url": image_url, "mid": mid})
        return {"message_id": mid}

    async def resolve_ig_url_to_media_id(self, ig_url: str) -> str | None:
        self.calls.append({"type": "resolve_ig_url_to_media_id", "ig_url": ig_url})
        return None

    async def get_user_info(self, user_id: str) -> dict:
        self.calls.append({"type": "get_user_info", "user_id": user_id})
        return {"name": "TestCustomer"}

    async def get_media_shortcode(self, media_id: str) -> str | None:
        self.calls.append({"type": "get_media_shortcode", "media_id": media_id})
        return None


class FakeWhatsAppClient:
    """Drop-in for app.integrations.whatsapp.WhatsAppClient — manual-verify pings."""

    def __init__(self, *args: Any, **kwargs: Any):
        self.calls: list[dict[str, Any]] = []

    async def send_message(self, to: str, text: str) -> dict:
        self.calls.append({"type": "send_message", "to": to, "text": text})
        return {"status": "ok"}


class FakeSarvamFailingClient:
    """Sarvam stand-in that always raises.

    Production today has SARVAM_API_KEY unset, which makes Sarvam raise on
    every call and the bot fall back to claude.generate_reply. We model the
    same code path so scenarios exercise what users actually experience.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        pass

    async def generate_reply(self, context: dict) -> str:
        raise RuntimeError("FakeSarvamFailingClient: forcing Claude fallback")
