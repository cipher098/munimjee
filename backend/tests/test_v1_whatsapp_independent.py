"""Independent no-DB regressions of exact frozen helpers; no provider calls.

No raw command/challenge is emitted by assertions or artifact output.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.config import settings
from app.services import whatsapp_test_authority as authority
from app.services.whatsapp_test_protocol import (
    RESERVED_NAMESPACE, SessionBinding, challenge_command, reserved_command,
)


@pytest.mark.asyncio
async def test_reserved_secret_in_provider_mid_never_reaches_any_retained_message_scalar(monkeypatch):
    monkeypatch.setattr(settings, 'V1_CHANNEL_TESTS_ENABLED', False)
    command = challenge_command('synthetic-independent-only', UUID(int=5),
        SessionBinding(UUID(int=1), UUID(int=2), UUID(int=3), 0))
    rows = []
    db = SimpleNamespace(scalar=AsyncMock(return_value=None), add=rows.append, flush=AsyncMock())
    account = SimpleNamespace(seller_id=UUID(int=1), phone_number_id='12345', waba_id='67890')
    at = datetime(2026, 10, 18, tzinfo=timezone.utc)
    packet = {'id': 'wamid.' + command, 'from': '919876543210',
        'timestamp': str(int(at.timestamp())), 'type': 'text', 'text': {'body': 'ordinary text'}}
    assert await authority.intercept_reserved(db, account, packet, received_at=at) is True
    # Keep raw packet/command out of pytest assertion diagnostics.
    retained_reserved_metadata = any(reserved_command(getattr(row, field, None))
        for row in rows for field in ('provider_message_id', 'idempotency_key'))
    assert retained_reserved_metadata is False
    assert rows == []


@pytest.mark.asyncio
async def test_cancelled_graph_waiters_keep_admission_until_the_underlying_jobs_finish(monkeypatch):
    """Four interrupted callers cannot create an unbounded pending IO backlog."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock
    from app.services import whatsapp_signup_provider as provider

    release, all_started = Event(), Event()
    count_lock = Lock()
    started = 0
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='independent-wa-fixture')

    class Isolated(provider.PinnedGraphTransport):
        _pool = pool
        _lock = Lock()
        _inflight = set()

    def bounded_fake_io(request):
        nonlocal started
        with count_lock:
            started += 1
            if started == 4:
                all_started.set()
        if not release.wait(2):
            raise RuntimeError('Synthetic fixture deadline, no network')
        return {}

    monkeypatch.setattr(Isolated, '_request', staticmethod(bounded_fake_io))
    request = provider.GraphRequest('GET', '/v26.0/oauth/access_token',
        query=(('client_id', '123'), ('client_secret', 'synthetic-only'), ('code', 'synthetic-only')))
    transport = Isolated()
    tasks = [asyncio.create_task(transport.request(request)) for _ in range(4)]
    try:
        async def wait_started():
            while not all_started.is_set():
                await asyncio.sleep(.001)
        await asyncio.wait_for(wait_started(), 1)
        for task in tasks:
            task.cancel()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(value, asyncio.CancelledError) for value in outcomes)
        with pytest.raises(provider.SignupProviderError):
            await transport.request(request)
        assert started == 4
        assert len(Isolated._inflight) == 4
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        pool.shutdown(wait=True)
