"""Instagram-direct API client — OAuth + send DMs/images.

Uses the "Instagram API with Instagram Login" flow:
  - OAuth: instagram.com/oauth/authorize (NOT facebook.com)
  - Token exchange: api.instagram.com/oauth/access_token
  - Long-lived exchange: graph.instagram.com/access_token?grant_type=ig_exchange_token
  - Messaging: graph.instagram.com/<IG_USER_ID>/messages

The old Facebook Login + Page-based flow is gone. No Facebook Page needed.
Sellers just need a Business/Creator Instagram account.
"""
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Scopes for the Instagram-direct flow. The "Manage messaging & content on
# Instagram" use case grants these without App Review for the app's developers
# and testers; production sellers need App Review.
INSTAGRAM_OAUTH_SCOPES = ",".join([
    "instagram_business_basic",
    "instagram_business_manage_messages",
])


def build_oauth_authorize_url(redirect_uri: str, state: str) -> str:
    """Build the Instagram OAuth dialog URL the seller should visit.

    Goes through instagram.com (not facebook.com) — returns an IG user access
    token bound to the IG account directly, no Page hop.
    """
    from urllib.parse import urlencode
    params = {
        "client_id": settings.INSTAGRAM_APP_ID,
        "redirect_uri": redirect_uri,
        "scope": INSTAGRAM_OAUTH_SCOPES,
        "response_type": "code",
        "state": state,
    }
    return f"https://www.instagram.com/oauth/authorize?{urlencode(params)}"


async def exchange_code_for_user_token(code: str, redirect_uri: str) -> dict:
    """Exchange the OAuth `code` for a short-lived IG user access token (~1 hour).

    Returns the full response dict: {"access_token": "...", "user_id": "..."}
    api.instagram.com expects form-encoded POST, NOT JSON, NOT GET.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id": settings.INSTAGRAM_APP_ID,
                "client_secret": settings.INSTAGRAM_APP_SECRET,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        if response.status_code != 200:
            logger.error("IG OAuth code exchange failed %d: %s", response.status_code, response.text)
        response.raise_for_status()
        data = response.json()
        logger.info(
            "IG code exchange OK — user_id=%s permissions=%s token_prefix=%s",
            data.get("user_id"),
            data.get("permissions"),
            str(data.get("access_token", ""))[:20],
        )
        return data


async def exchange_for_long_lived_token(short_lived_token: str) -> str:
    """Exchange a short-lived IG token for a long-lived one (~60 days)."""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            "https://graph.instagram.com/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": settings.INSTAGRAM_APP_SECRET,
                "access_token": short_lived_token,
            },
        )
        if response.status_code != 200:
            logger.error("IG long-lived exchange failed %d: %s", response.status_code, response.text)
        response.raise_for_status()
        return response.json()["access_token"]


async def subscribe_ig_user_to_messages(ig_user_id: str, user_token: str) -> dict:
    """Subscribe this IG account to the app's `messages` webhook.

    App-level webhook config in the dashboard isn't enough — Meta also needs an
    explicit per-account subscribe so it knows to fire events for this seller.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"https://graph.instagram.com/{settings.INSTAGRAM_API_VERSION}/{ig_user_id}/subscribed_apps",
            params={
                "subscribed_fields": "messages",
                "access_token": user_token,
            },
        )
        if response.status_code != 200:
            logger.error("IG subscribe_apps failed %d: %s", response.status_code, response.text)
        response.raise_for_status()
        return response.json()


async def fetch_ig_user(user_token: str) -> dict:
    """Return the IG account that owns this token.

    Endpoint: graph.instagram.com/me (NOT graph.facebook.com — that returns the
    Facebook user and rejects the `username` field as deprecated).

    Returns: {"user_id": "<numeric>", "username": "...", "name": "...", "account_type": "BUSINESS|CREATOR"}
    """
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"https://graph.instagram.com/{settings.INSTAGRAM_API_VERSION}/me",
            params={
                "fields": "user_id,username,name,account_type",
                "access_token": user_token,
            },
        )
        if response.status_code != 200:
            logger.error("fetch_ig_user failed %d: %s", response.status_code, response.text)
        response.raise_for_status()
        data = response.json()
        logger.info(
            "fetch_ig_user: user_id=%s username=%s name=%s account_type=%s",
            data.get("user_id"), data.get("username"), data.get("name"), data.get("account_type"),
        )
        return data


class InstagramClient:
    """Sends DMs + images via the Instagram Graph API.

    Constructor signature kept the same — `fb_page_id` now holds the IG user
    id (set by the OAuth callback). URLs hit graph.instagram.com instead of
    graph.facebook.com.
    """

    def __init__(self, ig_user_token: str, fb_page_id: str) -> None:
        self._token = ig_user_token
        self.fb_page_id = fb_page_id  # actually the IG user id in the new flow
        self._base_url = f"https://graph.instagram.com/{settings.INSTAGRAM_API_VERSION}"

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
                },
            )
            if response.status_code != 200:
                logger.error(
                    "Instagram send_image failed %d: %s", response.status_code, response.text
                )
            response.raise_for_status()
            return response.json()
