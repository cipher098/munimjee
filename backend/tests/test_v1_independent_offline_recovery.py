"""Additional finite recovery/load acceptance at actual module/service seams."""
import asyncio
from concurrent.futures import Future
from datetime import timedelta
import time

import pytest

from app.services import imports_v1 as service
from app.v1.imports import fetching, runner
from tests.independent_offline_recovery_qa import MemorySessions, FiniteFetcher, run_finite


@pytest.mark.asyncio
async def test_finite_import_burst_active_redelivery_and_repeat_drain_have_exact_effects(monkeypatch, record_property):
    started_at = time.monotonic()
    store = MemorySessions()
    store.install(monkeypatch)
    gate = asyncio.Event()
    fetcher = FiniteFetcher(store, gate=gate)
    rows = list(store.jobs.values())
    active = asyncio.create_task(run_finite(store, fetcher, rows))
    try:
        await fetcher.wait_for_calls(4)
        # Eight duplicate deliveries while the first four claims remain leased.
        duplicates = await run_finite(store, fetcher, rows[:4] * 2)
        assert duplicates == [False] * 8
        assert len(fetcher.calls) == 4 and not store.drafts
        gate.set()
        assert await active == [True] * 24
        assert fetcher.peak == 4 and fetcher.active == 0
        assert len(fetcher.calls) == len(store.drafts) == len(store.audits) == 24
        assert all(row.state == "review_required" and row.attempts == 1 and row.candidate_count == 1
                   and row.lease_token is None for row in rows)
        assert all(row.document["extracted"]["stock"] is None and row.document["extracted"]["options"] is None
                   for row in store.drafts.values())
        assert await runner.drain_jobs(store, limit=20, fetcher=fetcher) == 0
        assert await run_finite(store, fetcher, rows) == [False] * 24
        assert len(store.drafts) == len(store.audits) == len(fetcher.calls) == 24
        assert fetcher.total_body_bytes <= 24 * 4096
        for key, value in {"original_jobs":24,"active_redeliveries":8,"peak_fetch_callers":fetcher.peak,
                           "body_bytes":fetcher.total_body_bytes,"drafts":len(store.drafts),
                           "elapsed_seconds_informational":time.monotonic()-started_at}.items():
            record_property(key,value)
    finally:
        gate.set()
        if not active.done():
            active.cancel()
        await asyncio.gather(active, return_exceptions=True)


@pytest.mark.asyncio
async def test_four_interrupted_claims_expire_then_bounded_recovery_drains_without_duplicates(monkeypatch, record_property):
    started_at = time.monotonic()
    store = MemorySessions()
    store.install(monkeypatch)
    interrupted = FiniteFetcher(store, gate=asyncio.Event())
    rows = list(store.jobs.values())
    tasks = [asyncio.create_task(service.run_job(store, row.business_id, row.id, fetcher=interrupted))
             for row in rows[:4]]
    try:
        await interrupted.wait_for_calls(4)
        old_tokens = [row.lease_token for row in rows[:4]]
        for task in tasks:
            task.cancel()
        assert all(isinstance(value, asyncio.CancelledError) for value in await asyncio.gather(*tasks, return_exceptions=True))
        assert all(row.state == "running" and row.attempts == 1 for row in rows[:4])
        assert len(store.drafts) == 0 and interrupted.active == 0
        store.clock += timedelta(seconds=61)
        recovered = FiniteFetcher(store)
        # The queue, real runner and real service choose and process rows.
        assert await runner.drain_jobs(store, limit=20, fetcher=recovered) == 20
        assert await runner.drain_jobs(store, limit=20, fetcher=recovered) == 4
        assert await runner.drain_jobs(store, limit=20, fetcher=recovered) == 0
        assert store.queue_batch_sizes == [20, 4, 0]
        assert len(store.drafts) == len(store.audits) == len(recovered.calls) == 24
        assert recovered.peak == 1  # Actual drain is intentionally serial.
        assert [row.attempts for row in rows] == [2] * 4 + [1] * 20
        assert all(row.state == "review_required" and row.lease_token is None for row in rows)
        assert all(old is not None for old in old_tokens)
        assert await run_finite(store, recovered, rows) == [False] * 24
        assert len(recovered.calls) == 24
        for key, value in {"interrupted_jobs":4,"recovered_jobs":24,"drain_batches":"20,4,0",
                           "peak_recovery_fetch_callers":recovered.peak,"drafts":len(store.drafts),
                           "elapsed_seconds_informational":time.monotonic()-started_at}.items():
            record_property(key,value)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_transport_burst_cancelled_work_retains_four_slots_then_admission_recovers(monkeypatch, record_property):
    started_at = time.monotonic()
    class FinitePool:
        def __init__(self):
            self.futures = []
        def submit(self, *args):
            assert len(self.futures) < 5, "Finite workload exceeded original envelope"
            future = Future()
            self.futures.append(future)
            return future
    pool = FinitePool()
    monkeypatch.setattr(fetching.PinnedHTTPTransport, "_pool", pool)
    monkeypatch.setattr(fetching.PinnedHTTPTransport, "_inflight", set())
    transport = fetching.PinnedHTTPTransport()
    deadline = time.monotonic() + 5
    limits = fetching.FetchLimits(max_bytes=4096, timeout_seconds=0.2)
    calls = [asyncio.create_task(transport.request("https://shop.example.com/", "93.184.216.34", limits)) for _ in range(12)]
    try:
        await asyncio.sleep(0)
        assert len(pool.futures) == len(transport._inflight) == 4
        busy = await asyncio.gather(*calls[4:], return_exceptions=True)
        assert all(isinstance(value, fetching.FetchError) and value.code == "transport_busy" for value in busy)
        for task in calls[:4]:
            task.cancel()
        assert all(isinstance(value, asyncio.CancelledError) for value in await asyncio.gather(*calls[:4], return_exceptions=True))
        with pytest.raises(fetching.FetchError, match="transport_busy"):
            await transport.request("https://shop.example.com/", "93.184.216.34", limits)
        assert len(pool.futures) == 4 and not any(future.cancelled() for future in pool.futures)
        response = fetching.FetchResponse(200, {"content-type": "application/json"}, b"{}", "93.184.216.34")
        for future in pool.futures:
            future.set_result(response)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        resumed = asyncio.create_task(transport.request("https://shop.example.com/", "93.184.216.34", limits))
        await asyncio.sleep(0)
        assert len(pool.futures) == 5 and len(transport._inflight) == 1
        pool.futures[-1].set_result(response)
        assert await asyncio.wait_for(resumed, 0.2) == response
        assert time.monotonic() < deadline
        for key, value in {"burst_callers":12,"admitted_initial":4,"expected_busy_rejections":8,
                           "recovery_admissions":1,"retained_slot_ceiling":4,
                           "elapsed_seconds_informational":time.monotonic()-started_at}.items():
            record_property(key,value)
    finally:
        for future in pool.futures:
            if not future.done():
                future.set_result(fetching.FetchResponse(200, {}, b"", "93.184.216.34"))
        for task in calls:
            if not task.done():
                task.cancel()
        await asyncio.gather(*calls, return_exceptions=True)
