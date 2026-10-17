"""Instagram profile and media calls must not leak tokens through URL logging."""
import httpx
import pytest
from app.integrations import instagram

@pytest.mark.asyncio
@pytest.mark.parametrize("method,arg", [("get_user_info", "customer"), ("get_media_shortcode", "media"), ("resolve_ig_url_to_media_id", "https://www.instagram.com/p/example/")])
async def test_graph_lookup_uses_authorization_header(monkeypatch, method, arg):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"name": "Test", "shortcode": "example", "media_id": "media"})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(instagram.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    await getattr(instagram.InstagramClient("test-secret", "seller"), method)(arg)
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer test-secret"
    assert "access_token" not in requests[0].url.params
    assert "test-secret" not in str(requests[0].url)
