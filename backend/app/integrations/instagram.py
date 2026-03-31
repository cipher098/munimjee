"""Instagram Graph API client — send DMs and images."""
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def exchange_for_long_lived_token(short_lived_token: str) -> str:
    """Exchange a short-lived token for a long-lived token (valid ~60 days)."""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            "https://graph.facebook.com/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "fb_exchange_token": short_lived_token,
            },
        )
        if response.status_code != 200:
            logger.error("Token exchange failed %d: %s", response.status_code, response.text)
        response.raise_for_status()
        data = response.json()
        return data["access_token"]


class InstagramClient:
    def __init__(self, ig_user_token: str, fb_page_id: str) -> None:
        self._token = ig_user_token
        self.fb_page_id = fb_page_id
        self._base_url = f"https://graph.facebook.com/{settings.META_API_VERSION}"

    async def send_message(self, recipient_id: str, text: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self._base_url}/{self.fb_page_id}/messages",
                headers={"Authorization": f"Bearer {self._token}"},
                json={
                    "recipient": {"id": recipient_id},
                    "message": {"text": text},
                    "messaging_type": "RESPONSE",
                },
            )
            if response.status_code != 200:
                logger.error(
                    "Instagram send_message failed %d: %s", response.status_code, response.text
                )
            response.raise_for_status()
            return response.json()

    async def send_image(self, recipient_id: str, image_url: str) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{self._base_url}/{self.fb_page_id}/messages",
                headers={"Authorization": f"Bearer {self._token}"},
                json={
                    "recipient": {"id": recipient_id},
                    "message": {
                        "attachment": {
                            "type": "image",
                            "payload": {"url": image_url, "is_reusable": True},
                        }
                    },
                    "messaging_type": "RESPONSE",
                },
            )
            if response.status_code != 200:
                logger.error(
                    "Instagram send_image failed %d: %s", response.status_code, response.text
                )
            response.raise_for_status()
            return response.json()
