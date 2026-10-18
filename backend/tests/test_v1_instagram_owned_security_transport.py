"""Independent bounded transport tests; no DNS or socket connection is performed."""
import asyncio
from threading import Event
import time

import pytest

from app.v1.imports.fetching import FetchError
from app.v1.imports import instagram_owned_transport as transport

PUBLIC = "93.184.216.34"
TOKEN = "SYNTHETIC-TRANSPORT-SECRET"
GRAPH = "https://graph.instagram.com/v25.0/me?fields=user_id,account_type"
CDN = "https://scontent.cdninstagram.com/item.jpg?oe=ABC&sig=signed-ephemeral"


def request(**changes):
    values = dict(url=GRAPH, pinned_ip=PUBLIC, token=TOKEN, max_bytes=256000, timeout_seconds=0.05)
    values.update(changes)
    return transport.OwnedRequest(**values)


@pytest.mark.parametrize("url", [
    "http://graph.instagram.com/v25.0/me", "https://graph.facebook.com/v25.0/me",
    "https://graph.instagram.com.attacker.example/v25.0/me", "https://user:pass@graph.instagram.com/v25.0/me",
    "https://graph.instagram.com:8443/v25.0/me", "https://graph.instagram.com/v25.0/me#frag",
    "https://graph.instagram.com/v25.0/me?access_token=secret", "https://graph.instagram.com/v25.0/messages",
    "https://graph.instagram.com/v25.0/instagram_oembed", "https://graph.instagram.com/v25.0/../../me",
    "https://graph.instagram.com./v25.0/me", "https://graph.instagram.com/v25.0/me\r\nX-Auth:bad",
])
def test_security_transport_graph_authority_path_and_no_query_auth(url):
    with pytest.raises(FetchError):
        transport.checked_url(url, authenticated=True)


def test_security_transport_no_credential_or_signed_url_in_dto_repr():
    assert TOKEN not in repr(request()) and GRAPH not in repr(request())
    assert CDN not in repr(request(url=CDN, token=None))
    result = transport.OwnedResponse(200, {"location": CDN}, TOKEN.encode(), PUBLIC)
    assert TOKEN not in repr(result) and CDN not in repr(result)


@pytest.mark.asyncio
async def test_security_transport_thread_admission_retains_cancelled_work(monkeypatch):
    release, entered = Event(), []
    def blocking(value):
        entered.append(value)
        release.wait(2)
        return transport.OwnedResponse(200, {}, b"{}", PUBLIC)
    monkeypatch.setattr(transport.PinnedOwnedTransport, "_request", staticmethod(blocking))
    client = transport.PinnedOwnedTransport()
    tasks = [asyncio.create_task(client.request(request())) for _ in range(4)]
    try:
        deadline = time.monotonic() + 1
        while len(entered) < 4 and time.monotonic() < deadline:
            await asyncio.sleep(0.001)
        assert len(entered) == 4
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with pytest.raises(FetchError, match="instagram_busy"):
            await client.request(request())
        assert len(entered) == 4
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        deadline = time.monotonic() + 1
        while any(not item.done() for item in client._inflight) and time.monotonic() < deadline:
            await asyncio.sleep(0.001)


@pytest.mark.parametrize("token,url", [(TOKEN, GRAPH), (None, CDN)])
def test_security_transport_builds_header_auth_and_identity_body_without_proxy(monkeypatch, token, url):
    calls = []
    class Response:
        status = 200
        chunks = [b"{}", b""]
        def getheaders(self):
            return [("Content-Type", "application/json"), ("Content-Length", "2")]
        def read1(self, count):
            return self.chunks.pop(0)
    class Socket:
        def getpeername(self):
            return (PUBLIC, 443)
        def settimeout(self, timeout):
            assert 0 < timeout <= 1
    class Connection:
        sock = Socket()
        def __init__(self, host, pinned, timeout):
            calls.append((host, pinned, timeout))
        def connect(self):
            pass
        def request(self, method, target, headers):
            calls.append((method, target, headers))
        def getresponse(self):
            return Response()
        def close(self):
            calls.append("closed")
    monkeypatch.setattr(transport, "PinnedHTTPSConnection", Connection)
    result = transport.PinnedOwnedTransport._request(request(url=url, token=token, timeout_seconds=1))
    assert result.body == b"{}"
    assert calls[0][:2] == ("graph.instagram.com" if token else "scontent.cdninstagram.com", PUBLIC)
    method, target, headers = calls[1]
    assert method == "GET" and headers["Accept-Encoding"] == "identity"
    assert headers.get("Authorization") == ("Bearer " + TOKEN if token else None)
    assert "Cookie" not in headers and "Proxy-Authorization" not in headers
    assert TOKEN not in target and calls[-1] == "closed"


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_security_transport_error_bodies_are_never_downloaded(monkeypatch, status):
    class Response:
        def getheaders(self):
            return [("Location", "https://attacker.example/?token=" + TOKEN)]
        def read1(self, count):
            pytest.fail("Error/redirect body must never be read")
    Response.status = status
    class Connection:
        sock = None
        def __init__(self, *args):
            pass
        def connect(self):
            pass
        def request(self, *args, **kwargs):
            pass
        def getresponse(self):
            return Response()
        def close(self):
            pass
    monkeypatch.setattr(transport, "PinnedHTTPSConnection", Connection)
    assert transport.PinnedOwnedTransport._request(request()).body == b""
