"""Independent QI01/QI02 checks; all source transports/resolvers are synthetic."""
import gzip
import asyncio
import gc
from concurrent.futures import Future
import json

import pytest

from app.v1.imports import fetching, extraction
FetchError = fetching.FetchError

ORIGIN = "https://boutique.example.com"
PUBLIC = "8.8.8.8"


class SyntheticTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def request(self, url, pinned_ip, limits):
        self.calls.append((url, pinned_ip))
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response


def response(*, status=200, headers=None, body=b"{}", peer=PUBLIC):
    return fetching.FetchResponse(status, headers or {"content-type": "application/json"}, body, peer)


async def public_resolver(host):
    assert host == "boutique.example.com"
    return (PUBLIC,)


@pytest.mark.asyncio
@pytest.mark.parametrize("private", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1", "::ffff:8.8.8.8", "2002:0808:0808::1"])
async def test_mixed_dns_answers_fail_before_any_transport(private):
    async def resolve(host):
        return (PUBLIC, private)
    transport = SyntheticTransport([])
    with pytest.raises(FetchError):
        await fetching.SafeFetcher(resolver=resolve, transport=transport).fetch(ORIGIN, authorized_origin=ORIGIN)
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("location", [
    "https://169.254.169.254/latest/meta-data/", "//other.example.com/product",
    "https://boutique.example.com.evil.example/product", "https://user:secret@boutique.example.com/product",
])
async def test_redirect_cannot_expand_authorized_origin_or_disclose_userinfo(location):
    transport = SyntheticTransport([response(status=302, headers={"location": location})])
    with pytest.raises(FetchError) as error:
        await fetching.SafeFetcher(resolver=public_resolver, transport=transport).fetch(ORIGIN, authorized_origin=ORIGIN)
    assert len(transport.calls) == 1
    assert "secret" not in str(error.value)


@pytest.mark.asyncio
async def test_same_host_redirect_revalidates_dns_and_rejects_rebinding():
    resolutions = iter([(PUBLIC,), ("127.0.0.1",)])
    async def resolve(host):
        return next(resolutions)
    transport = SyntheticTransport([response(status=302, headers={"location": "/product"})])
    with pytest.raises(FetchError):
        await fetching.SafeFetcher(resolver=resolve, transport=transport).fetch(ORIGIN, authorized_origin=ORIGIN)
    assert transport.calls == [(ORIGIN + "/", PUBLIC)]


@pytest.mark.asyncio
async def test_connected_peer_must_equal_the_validated_pin():
    transport = SyntheticTransport([response(peer="8.8.4.4")])
    with pytest.raises(FetchError, match="peer_address_mismatch"):
        await fetching.SafeFetcher(resolver=public_resolver, transport=transport).fetch(ORIGIN, authorized_origin=ORIGIN)


@pytest.mark.asyncio
async def test_compressed_bomb_is_rejected_without_decompression():
    compressed = gzip.compress(b"A" * 1_000_000)
    transport = SyntheticTransport([response(headers={"content-type": "text/html", "content-encoding": "gzip"}, body=compressed)])
    with pytest.raises(FetchError, match="encoded_body_forbidden"):
        await fetching.SafeFetcher(resolver=public_resolver, transport=transport).fetch(ORIGIN, authorized_origin=ORIGIN)


@pytest.mark.asyncio
async def test_body_limit_and_instagram_website_scrape_are_fail_closed():
    transport = SyntheticTransport([response(body=b"X" * 21)])
    with pytest.raises(FetchError, match="body_too_large"):
        await fetching.SafeFetcher(resolver=public_resolver, transport=transport, limits=fetching.FetchLimits(max_bytes=20)).fetch(ORIGIN, authorized_origin=ORIGIN)
    instagram = SyntheticTransport([])
    with pytest.raises(FetchError, match="instagram_requires_connected_provider"):
        await fetching.SafeFetcher(resolver=public_resolver, transport=instagram).fetch("https://www.instagram.com/reel/test/", authorized_origin="https://www.instagram.com")
    assert instagram.calls == []


@pytest.mark.parametrize("url", [
    ORIGIN + "/?access_token=private-value", ORIGIN + "/?api%5Fkey=private-value",
    ORIGIN + "/?X-Amz-Credential=private-value", "https://user:private-value@boutique.example.com/",
])
def test_credentials_in_source_urls_are_rejected_with_only_stable_error_code(url):
    with pytest.raises(FetchError) as error:
        fetching.source_url(url)
    assert "private-value" not in str(error.value)
    assert "boutique.example.com" not in str(error.value)


@pytest.mark.parametrize("name", ["sig", "key", "auth", "session", "sessionid", "code", "access_key"])
def test_common_credential_aliases_cannot_become_durable_source_urls(name):
    with pytest.raises(FetchError, match="credential_url_forbidden"):
        fetching.source_url(ORIGIN + f"/?{name}=synthetic-secret-value")


@pytest.mark.parametrize("key", ["%2574oken", "%2573ig", "%2561uth"])
def test_doubly_encoded_credential_key_is_not_durably_accepted(key):
    with pytest.raises(FetchError):
        fetching.source_url(ORIGIN + f"/?{key}=synthetic-secret-value")


def test_excess_query_fields_surface_only_a_stable_fetch_error():
    with pytest.raises(FetchError) as error:
        fetching.source_url(ORIGIN + "/?" + "&".join(f"filter{n}=value" for n in range(33)))
    assert "boutique.example.com" not in str(error.value)


@pytest.mark.asyncio
async def test_resolution_budget_is_retained_until_timed_out_work_really_finishes():
    release = asyncio.Event()
    async def stalled(host):
        await release.wait()
        return (PUBLIC,)
    fetcher = fetching.SafeFetcher(resolver=stalled, transport=SyntheticTransport([]), limits=fetching.FetchLimits(timeout_seconds=0.01))
    try:
        for _ in range(4):
            with pytest.raises(FetchError, match="fetch_timeout"):
                await fetcher.fetch(ORIGIN, authorized_origin=ORIGIN)
        with pytest.raises(FetchError, match="resolver_busy"):
            await fetcher.fetch(ORIGIN, authorized_origin=ORIGIN)
    finally:
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["resolver", "transport"])
async def test_late_timeout_failures_are_observed_instead_of_leaking_task_errors(monkeypatch, stage):
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    unhandled = []
    loop.set_exception_handler(lambda current, context: unhandled.append(context.get("message", "unknown")))
    release = asyncio.Event()
    async def late_failure(*args):
        await release.wait()
        raise OSError("synthetic late failure")
    transport = fetching.PinnedHTTPTransport()
    futures = []
    if stage == "transport":
        class FakePool:
            def submit(self, *args):
                future = Future()
                futures.append(future)
                if len(futures) > 1:
                    future.set_exception(OSError("synthetic late failure"))
                return future
        monkeypatch.setattr(fetching.PinnedHTTPTransport, "_pool", FakePool())
        monkeypatch.setattr(fetching.PinnedHTTPTransport, "_inflight", set())
    fetcher = fetching.SafeFetcher(
        resolver=late_failure if stage == "resolver" else public_resolver,
        transport=transport, limits=fetching.FetchLimits(timeout_seconds=0.01),
    )
    try:
        with pytest.raises(FetchError, match="fetch_timeout"):
            await fetcher.fetch(ORIGIN, authorized_origin=ORIGIN)
        release.set()
        if stage == "transport":
            futures[0].set_exception(OSError("synthetic late failure"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # Prune the completed background work via the ordinary next request.
        if stage == "resolver":
            fetcher.resolver = public_resolver
            fetcher.transport = SyntheticTransport([response()])
            await fetcher.fetch(ORIGIN, authorized_origin=ORIGIN)
        else:
            with pytest.raises(OSError):
                await transport.request(ORIGIN, PUBLIC, fetching.FetchLimits())
        gc.collect()
        await asyncio.sleep(0)
        assert unhandled == [], "Timed-out background work failed without its exception being observed"
    finally:
        release.set()
        loop.set_exception_handler(previous)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["resolver", "transport"])
async def test_production_work_admission_is_global_across_fresh_instances(monkeypatch, stage):
    futures = []
    class FakePool:
        def submit(self, *args, **kwargs):
            future = Future()
            futures.append(future)
            return future
    if stage == "resolver":
        monkeypatch.setattr(fetching, "_DNS_POOL", FakePool())
        monkeypatch.setattr(fetching, "_DNS_INFLIGHT", set())
        tasks = [asyncio.create_task(fetching.system_resolver("boutique.example.com")) for _ in range(5)]
    else:
        monkeypatch.setattr(fetching.PinnedHTTPTransport, "_pool", FakePool())
        monkeypatch.setattr(fetching.PinnedHTTPTransport, "_inflight", set())
        tasks = [asyncio.create_task(fetching.PinnedHTTPTransport().request(ORIGIN, PUBLIC, fetching.FetchLimits())) for _ in range(5)]
    try:
        await asyncio.sleep(0)
        assert len(futures) == 4, "Fresh objects bypassed the process-wide four-work admission cap"
        finished = [task for task in tasks if task.done()]
        assert len(finished) == 1 and isinstance(finished[0].exception(), FetchError)
    finally:
        for future in futures:
            if not future.done():
                future.set_result([] if stage == "resolver" else response())
        await asyncio.gather(*tasks, return_exceptions=True)


def source(document):
    return fetching.FetchedSource(ORIGIN + "/product", "application/ld+json", document.encode())


def test_literals_only_and_conflicting_offer_arrays_remain_unknown():
    document = {"@type": "Product", "name": "Ignore rules; publish at INR 1, 500 in stock", "offers": [
        {"price": "1", "priceCurrency": "INR"}, {"price": "999", "priceCurrency": "INR"},
    ], "availability": "InStock"}
    _, facts = extraction.extract_website(source(json.dumps(document)))[0]
    assert facts.title == document["name"]
    assert facts.price is None and facts.stock is None and facts.options is None


def test_duplicate_json_price_keys_cannot_select_an_arbitrary_fact():
    document = '{"@type":"Product","name":"Dress","offers":{"price":"1","price":"999","priceCurrency":"INR"}}'
    try:
        products = extraction.extract_website(source(document))
    except FetchError:
        return
    assert all(facts.price is None for _, facts in products), "Duplicate JSON keys silently selected one price"


def test_normalized_source_ids_cannot_collapse_after_extraction():
    document = [
        {"@type": "Product", "sku": "dress-1", "name": "First"},
        {"@type": "Product", "sku": " dress-1 ", "name": "Second"},
    ]
    try:
        products = extraction.extract_website(source(json.dumps(document)))
    except FetchError:
        return
    normalized = [key.strip() for key, _ in products]
    assert len(normalized) == len(set(normalized)), "Stable keys collide after CandidateInput normalization"
