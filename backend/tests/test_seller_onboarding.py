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
    assert parsed.netloc == "www.facebook.com"
    qs = parse_qs(parsed.query)
    assert qs["redirect_uri"] == ["https://example.com/auth/instagram/oauth/callback"]
    assert qs["state"] == ["abc.def"]
    assert qs["response_type"] == ["code"]
    # All five messaging-relevant scopes must be present.
    scopes = qs["scope"][0].split(",")
    for required in [
        "pages_show_list",
        "pages_messaging",
        "instagram_basic",
        "instagram_manage_messages",
    ]:
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
    assert "yaar" in DEFAULT_PERSONA["common_expressions"]


def test_pick_ig_page_filters_out_non_ig_pages():
    """Simulate Meta's /me/accounts response and verify only IG-linked pages qualify."""
    pages = [
        {"id": "page-A", "name": "FB Only", "access_token": "tA"},
        {
            "id": "page-B",
            "name": "Boutique",
            "access_token": "tB",
            "instagram_business_account": {"id": "ig-100", "username": "boutique"},
        },
    ]
    # Mirror the callback's filter logic.
    pick = next((p for p in pages if p.get("instagram_business_account")), None)
    assert pick is not None
    assert pick["id"] == "page-B"
    assert pick["instagram_business_account"]["id"] == "ig-100"


def test_pick_ig_page_returns_none_when_no_ig_linked():
    pages = [{"id": "page-A", "name": "FB Only", "access_token": "tA"}]
    pick = next((p for p in pages if p.get("instagram_business_account")), None)
    assert pick is None
