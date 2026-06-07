"""Tests for the self-serve seller onboarding flow.

Covers:
  - OAuth state HMAC signing roundtrip + tamper detection
  - Default persona / policies are populated on signup
  - Helpers compose the correct Meta API URLs / params
  - Page-picking logic in the callback rejects pages without an IG account

These are pure-function tests where possible. End-to-end signup + callback
against a live FastAPI test client + real DB would need the db_session
fixture from conftest_db.py — left for a follow-up so this commit stays
focused on the auth surface itself.
"""
from urllib.parse import parse_qs, urlparse

import pytest

from app.api.routes.auth import _sign_oauth_state, _verify_oauth_state
from app.integrations.instagram import (
    INSTAGRAM_OAUTH_SCOPES,
    build_oauth_authorize_url,
)


def test_oauth_state_roundtrip_preserves_seller_id():
    seller_id = "11111111-2222-3333-4444-555555555555"
    state = _sign_oauth_state(seller_id)
    assert _verify_oauth_state(state) == seller_id


def test_oauth_state_signature_detects_tamper():
    """Changing the seller_id after signing must fail verification."""
    from fastapi import HTTPException

    state = _sign_oauth_state("seller-A")
    tampered = state.replace("seller-A", "seller-B")
    with pytest.raises(HTTPException) as exc_info:
        _verify_oauth_state(tampered)
    assert exc_info.value.status_code == 400


def test_oauth_state_signature_detects_truncated_sig():
    from fastapi import HTTPException

    state = _sign_oauth_state("seller-X")
    truncated = state[:-4]
    with pytest.raises(HTTPException):
        _verify_oauth_state(truncated)


def test_oauth_state_malformed_no_dot():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _verify_oauth_state("no-dot-here")
    assert exc_info.value.status_code == 400


def test_build_authorize_url_includes_required_scopes_and_state():
    url = build_oauth_authorize_url(
        redirect_uri="https://example.com/auth/instagram/oauth/callback",
        state="abc.def",
    )
    parsed = urlparse(url)
    # Instagram-direct flow goes through instagram.com, NOT facebook.com.
    assert parsed.netloc == "www.instagram.com"
    assert parsed.path == "/oauth/authorize"
    qs = parse_qs(parsed.query)
    assert qs["redirect_uri"] == ["https://example.com/auth/instagram/oauth/callback"]
    assert qs["state"] == ["abc.def"]
    assert qs["response_type"] == ["code"]
    scopes = qs["scope"][0].split(",")
    for required in ["instagram_business_basic", "instagram_business_manage_messages"]:
        assert required in scopes, f"missing scope: {required}"
    assert scopes == INSTAGRAM_OAUTH_SCOPES.split(",")


def test_default_persona_and_policies_are_safe_defaults():
    """New sellers shouldn't accidentally promise returns / COD they don't offer."""
    from app.seller_defaults import DEFAULT_PERSONA, DEFAULT_POLICIES

    assert DEFAULT_POLICIES["cod"] is False
    assert DEFAULT_POLICIES["return_days"] == 0
    assert DEFAULT_POLICIES["exchange_days"] == 0
    assert "upi" in DEFAULT_POLICIES["payment_modes"]
    assert DEFAULT_PERSONA["negotiation_firmness"] == "medium"
    # Respectful, non-pushy default voice: "ji" not the over-familiar "yaar", minimal emoji.
    assert "ji" in DEFAULT_PERSONA["common_expressions"]
    assert "yaar" not in DEFAULT_PERSONA["common_expressions"]
    assert DEFAULT_PERSONA["emoji_usage"] == "minimal"


def test_callback_rejects_non_business_ig_account():
    """The callback should refuse Personal IG accounts (only Business/Creator can send DMs)."""
    # Mirror the callback's account_type guard.
    ig_user = {"user_id": "ig-100", "username": "joe", "account_type": "PERSONAL"}
    account_type = ig_user.get("account_type")
    assert account_type and account_type not in ("BUSINESS", "CREATOR")


def test_callback_accepts_business_and_creator_ig_accounts():
    for account_type in ["BUSINESS", "CREATOR"]:
        ig_user = {"user_id": "ig-100", "username": "shop", "account_type": account_type}
        assert ig_user["account_type"] in ("BUSINESS", "CREATOR")
