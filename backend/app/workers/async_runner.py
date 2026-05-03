"""Utility for running async coroutines from synchronous Celery tasks."""
import asyncio
import logging

logger = logging.getLogger(__name__)


def _suppress_loop_closed(loop, context):
    """Silence 'Event loop is closed' noise from httpx transport cleanup.

    httpx closes TLS connections by calling loop.call_soon() from inside a
    synchronous transport.close(), which fires after all async tasks have
    already completed. There is no way to drain these — they are not tasks.
    The Celery task itself succeeds; this is pure cleanup noise.
    """
    exc = context.get("exception")
    if isinstance(exc, RuntimeError) and "Event loop is closed" in str(exc):
        return
    loop.default_exception_handler(context)


def run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_exception_handler(_suppress_loop_closed)
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            asyncio.set_event_loop(None)
