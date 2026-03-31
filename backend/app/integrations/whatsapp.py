"""WhatsApp Cloud API client — seller owner pings + SMS forwarding."""
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class WhatsAppClient:
    def __init__(self) -> None:
        self._api_url = settings.WHATSAPP_API_URL
        self._token = settings.WHATSAPP_API_TOKEN
        self._phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID

    async def send_message(self, to: str, text: str) -> dict:
        if not self._token or not self._phone_number_id:
            raise RuntimeError("WhatsApp API not configured")

        url = f"{self._api_url}/{self._phone_number_id}/messages"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {"body": text},
                },
            )
            if response.status_code != 200:
                logger.error(
                    "WhatsApp send_message failed %d: %s", response.status_code, response.text
                )
            response.raise_for_status()
            return response.json()
