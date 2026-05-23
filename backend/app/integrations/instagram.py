"""Instagram Graph API client — send DMs and images."""
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Scopes required to read pages, receive DMs, and reply on Instagram. All five
# are needed for the messaging webhook to actually flow:
#   - pages_show_list, pages_manage_metadata: list the user's pages, subscribe webhook
#   - pages_messaging: send/receive page messages
#   - instagram_basic: identify the linked IG business account
#   - instagram_manage_messages: actually send/receive IG DMs
#   - business_management: needed when the IG account is owned by a Business Manager
INSTAGRAM_OAUTH_SCOPES = ",".join([
    "pages_show_list",
    "pages_manage_metadata",
    "pages_messaging",
    "instagram_basic",
    "instagram_manage_messages",
    "business_management",
])


def build_oauth_authorize_url(redirect_uri: str, state: str) -> str:
    """Build the Facebook Login dialog URL the seller should visit."""
    from urllib.parse import urlencode
    params = {
        "client_id": settings.META_APP_ID,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": INSTAGRAM_OAUTH_SCOPES,
        "response_type": "code",
    }
    return f"https://www.facebook.com/{settings.META_API_VERSION}/dialog/oauth?{urlencode(params)}"


async def exchange_code_for_user_token(code: str, redirect_uri: str) -> str:
    """Exchange the OAuth `code` from the callback for a short-lived user access token."""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"https://graph.facebook.com/{settings.META_API_VERSION}/oauth/access_token",
            params={
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        if response.status_code != 200:
            logger.error("OAuth code exchange failed %d: %s", response.status_code, response.text)
        response.raise_for_status()
        return response.json()["access_token"]


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


async def list_user_pages(user_token: str) -> list[dict]:
    """List Facebook pages the OAuth user manages.

    Each returned page dict has at least:
      - id: Facebook page id
      - name
      - access_token: long-lived page access token (does not expire for pages)
      - instagram_business_account: {id} if a business IG account is linked
    """
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"https://graph.facebook.com/{settings.META_API_VERSION}/me/accounts",
            params={
                "access_token": user_token,
                "fields": "id,name,access_token,instagram_business_account{id,username}",
            },
        )
        if response.status_code != 200:
            logger.error("list_user_pages failed %d: %s", response.status_code, response.text)
        response.raise_for_status()
        return response.json().get("data", [])


async def subscribe_page_to_webhook(page_id: str, page_access_token: str) -> None:
    """Subscribe a Facebook page to our app's webhook so we receive DM events.

    Without this call, the OAuth grant lets us SEND messages but Meta won't
    POST customer DMs to /webhooks/instagram. This is the missing link sellers
    historically had to do by hand in the Meta dashboard.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"https://graph.facebook.com/{settings.META_API_VERSION}/{page_id}/subscribed_apps",
            params={
                "access_token": page_access_token,
                "subscribed_fields": "messages,messaging_postbacks,message_reactions",
            },
        )
        if response.status_code != 200:
            logger.error(
                "subscribe_page_to_webhook failed page=%s %d: %s",
                page_id, response.status_code, response.text,
            )
        response.raise_for_status()


class InstagramClient:
    def __init__(self, ig_user_token: str, fb_page_id: str) -> None:
        self._token = ig_user_token
        self.fb_page_id = fb_page_id
        self._base_url = f"https://graph.facebook.com/{settings.META_API_VERSION}"

    async def resolve_ig_url_to_media_id(self, ig_url: str) -> str | None:
        """Resolve an Instagram post/reel URL to its numeric media_id via oEmbed API."""
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self._base_url}/instagram_oembed",
                params={"url": ig_url, "fields": "media_id", "access_token": self._token},
            )
            if response.status_code != 200:
                logger.warning("oEmbed resolution failed %d: %s", response.status_code, response.text)
                return None
            return response.json().get("media_id")

    async def get_user_info(self, user_id: str) -> dict:
        """Fetch basic profile info (name) for an Instagram user by their IGSID."""
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self._base_url}/{user_id}",
                params={"fields": "name", "access_token": self._token},
            )
            if response.status_code != 200:
                logger.warning("get_user_info failed %d: %s", response.status_code, response.text)
                return {}
            return response.json()

    async def get_media_shortcode(self, media_id: str) -> str | None:
        """Resolve a media ID to its Instagram shortcode via Graph API."""
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self._base_url}/{media_id}",
                params={"fields": "shortcode", "access_token": self._token},
            )
            if response.status_code != 200:
                logger.warning("get_media_shortcode failed %d: %s", response.status_code, response.text)
                return None
            return response.json().get("shortcode")

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
