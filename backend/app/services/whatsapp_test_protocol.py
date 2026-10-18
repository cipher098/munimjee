"""Pure, credential-sanitized rules for native WA signup and fixed tests.

No transport, persistence or client-selected evidence classification lives here.
Reserved commands must be intercepted even when collection/setup flags are off.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

RESERVED_NAMESPACE = 'MUNIMJEE-WA-TEST'
REDACTED_COMMAND = 'WhatsApp connection-test command (redacted)'
FIXED_REPLY = 'This is a WhatsApp connection test from your business. No reply is required.'
FIXED_TEXT_VERSION = 'wa-connection-test.v1'
REQUIRED_GRANTS = frozenset({'whatsapp_business_management', 'whatsapp_business_messaging'})
GRAPH_ORIGIN = 'https://graph.facebook.com'
SDK_URL = 'https://connect.facebook.net/en_US/sdk.js'
MESSAGE_ORIGIN = 'https://www.facebook.com'
_IDENTIFIER = re.compile(r'[0-9]{1,40}', re.ASCII)
_COMMAND = re.compile(r'MUNIMJEE-WA-TEST:([A-Za-z0-9_-]{22})', re.ASCII)


class ProtocolError(ValueError):
    """Only a closed public code is retained; never provider bodies or input."""
    CODES = frozenset({'configuration_unavailable', 'configuration_mismatch', 'provider_response_invalid',
        'provider_grants_unverified', 'provider_expiry_unknown', 'provider_expiry_expired',
        'provider_account_unverified', 'command_invalid', 'provider_page_limit'})

    def __init__(self, code):
        super().__init__(code if code in self.CODES else 'provider_response_invalid')


def identifier(value):
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ProtocolError('provider_response_invalid')
    return value


def canonical_digest(secret: str, purpose: str, value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
    return hmac.new(secret.encode(), purpose.encode()+b'\x00'+encoded, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class SessionBinding:
    business_id: UUID
    user_id: UUID
    session_id: UUID
    auth_version: int

    def values(self):
        return [str(self.business_id), str(self.user_id), str(self.session_id), self.auth_version]


def bound_nonce(secret: str, attempt_id: UUID, binding: SessionBinding) -> str:
    raw = bytes.fromhex(canonical_digest(secret, 'wa-signup-nonce.v1', [str(attempt_id), *binding.values()]))
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def challenge_command(secret: str, test_id: UUID, binding: SessionBinding) -> str:
    raw = bytes.fromhex(canonical_digest(secret, 'wa-test-challenge.v1', [str(test_id), *binding.values()]))[:16]
    return RESERVED_NAMESPACE+':'+base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def reserved_command(text) -> bool:
    # A malformed/embedded marker is still redacted and withheld from ordinary
    # automation. This check is deliberately independent of feature gates.
    return type(text) is str and RESERVED_NAMESPACE.casefold() in text.casefold()


def command_digest(secret: str, text) -> str | None:
    if type(text) is not str:
        return None
    match = _COMMAND.fullmatch(text)
    if not match:
        return None
    # Base64's last two padding bits must be zero: reject alternate spellings.
    raw = base64.urlsafe_b64decode(match.group(1)+'==')
    if base64.urlsafe_b64encode(raw).rstrip(b'=').decode() != match.group(1):
        return None
    return canonical_digest(secret, 'wa-test-command.v1', text)


def embedded_configuration(settings):
    if not settings.V1_WHATSAPP_ONBOARDING_ENABLED:
        raise ProtocolError('configuration_unavailable')
    try:
        app_id, config_id = identifier(settings.WHATSAPP_EMBEDDED_APP_ID), identifier(settings.WHATSAPP_EMBEDDED_CONFIG_ID)
    except ProtocolError:
        raise ProtocolError('configuration_unavailable') from None
    if not settings.WHATSAPP_EMBEDDED_APP_SECRET or not settings.WHATSAPP_APP_SECRET:
        raise ProtocolError('configuration_unavailable')
    if not hmac.compare_digest(settings.WHATSAPP_EMBEDDED_APP_SECRET, settings.WHATSAPP_APP_SECRET):
        raise ProtocolError('configuration_mismatch')
    if settings.WHATSAPP_EMBEDDED_GRAPH_VERSION != 'v26.0' or not settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
        raise ProtocolError('configuration_unavailable')
    try:
        from cryptography.fernet import Fernet
        Fernet(settings.CHANNEL_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError, AttributeError):
        raise ProtocolError('configuration_unavailable') from None
    from urllib.parse import urlsplit
    try:
        origin = urlsplit(settings.PUBLIC_BASE_URL)
        if origin.scheme != 'https' or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment or origin.path not in ('', '/'):
            raise ValueError()
    except (ValueError, TypeError):
        raise ProtocolError('configuration_unavailable') from None
    return {'app_id': app_id, 'config_id': config_id, 'graph_version': 'v26.0',
        'sdk_url': SDK_URL, 'allowed_message_origin': MESSAGE_ORIGIN, 'auto_log_app_events': False, 'xfbml': False}


@dataclass(frozen=True)
class VerifiedToken:
    token: str = field(repr=False)
    app_id: str
    expires_at: datetime
    waba_ids: frozenset[str]


def verified_token(token_body, debug_body, *, app_id: str, now: datetime) -> VerifiedToken:
    """Strict compatibility assumption, not evidence of observed Meta wire data.

    Zero/absent expiry never means permanent. Both required grants must include
    an identical nonempty WABA target set; unfamiliar shapes fail closed.
    """
    try:
        if type(token_body) is not dict or set(token_body) != {'access_token'}:
            raise ProtocolError('provider_response_invalid')
        token = token_body['access_token']
        if type(token) is not str or not 1 <= len(token) <= 8192 or any(ord(c)<33 or ord(c)>126 for c in token):
            raise ProtocolError('provider_response_invalid')
        if type(debug_body) is not dict or type(debug_body.get('data')) is not dict:
            raise ProtocolError('provider_response_invalid')
        data = debug_body['data']
        if data.get('is_valid') is not True or data.get('app_id') != identifier(app_id):
            raise ProtocolError('provider_grants_unverified')
        scopes = data.get('scopes')
        granular = data.get('granular_scopes')
        if type(scopes) is not list or any(type(s) is not str for s in scopes) or not REQUIRED_GRANTS.issubset(scopes) or type(granular) is not list or len(granular)>50:
            raise ProtocolError('provider_grants_unverified')
        targets = {}
        for entry in granular:
            if type(entry) is not dict or type(entry.get('scope')) is not str:
                raise ProtocolError('provider_grants_unverified')
            scope = entry['scope']
            if scope in REQUIRED_GRANTS:
                ids = entry.get('target_ids')
                if scope in targets or type(ids) is not list or not 1 <= len(ids) <= 100:
                    raise ProtocolError('provider_grants_unverified')
                targets[scope] = frozenset(identifier(i) for i in ids)
        if set(targets) != REQUIRED_GRANTS or len(set(targets.values())) != 1:
            raise ProtocolError('provider_grants_unverified')
        expiry = data.get('expires_at')
        if type(expiry) is not int or expiry <= 0:
            raise ProtocolError('provider_expiry_unknown')
        try:
            expires_at = datetime.fromtimestamp(expiry, timezone.utc)
        except (ValueError, OSError, OverflowError):
            raise ProtocolError('provider_response_invalid') from None
        if expires_at <= now:
            raise ProtocolError('provider_expiry_expired')
        data_expiry = data.get('data_access_expires_at')
        if data_expiry is not None:
            if type(data_expiry) is not int or data_expiry <= 0:
                raise ProtocolError('provider_expiry_unknown')
            expires_at = min(expires_at, datetime.fromtimestamp(data_expiry, timezone.utc))
            if expires_at <= now:
                raise ProtocolError('provider_expiry_expired')
        return VerifiedToken(token, app_id, expires_at, next(iter(targets.values())))
    except ProtocolError:
        raise
    except (TypeError, KeyError, ValueError, OverflowError, OSError):
        raise ProtocolError('provider_response_invalid') from None


@dataclass(frozen=True)
class PhoneChoice:
    waba_id: str
    phone_number_id: str
    display_name: str
    display_phone_number: str
    # No undocumented inference from code_verification_status.
    provider_registration_status: str = 'unknown'


def phone_page(body, *, waba_id: str, verified: VerifiedToken):
    if identifier(waba_id) not in verified.waba_ids:
        raise ProtocolError('provider_account_unverified')
    if type(body) is not dict or type(body.get('data')) is not list or len(body['data'])>25:
        raise ProtocolError('provider_response_invalid')
    choices = []
    seen = set()
    for item in body['data']:
        if type(item) is not dict:
            raise ProtocolError('provider_response_invalid')
        phone = identifier(item.get('id'))
        name, display = item.get('verified_name'), item.get('display_phone_number')
        if phone in seen or type(name) is not str or not 1<=len(name)<=160 or type(display) is not str or not 1<=len(display)<=50 or any(ord(c)<32 for c in name+display):
            raise ProtocolError('provider_response_invalid')
        seen.add(phone)
        choices.append(PhoneChoice(waba_id, phone, name, display))
    paging = body.get('paging', {})
    if type(paging) is not dict:
        raise ProtocolError('provider_response_invalid')
    after = None
    if 'next' in paging:
        # Never follow the provider-supplied URL. Only use a bounded opaque
        # cursor with our fixed authority/path, preserving app token routing.
        cursors = paging.get('cursors')
        after = cursors.get('after') if type(cursors) is dict else None
        if type(after) is not str or not 1<=len(after)<=2048 or any(ord(c)<33 or ord(c)>126 for c in after):
            raise ProtocolError('provider_response_invalid')
    return tuple(choices), after
