"""Utility for running async coroutines from synchronous Celery tasks.

asyncio.run() closes the event loop immediately after the coroutine finishes,
which causes httpx's background connection-cleanup tasks to raise
RuntimeError('Event loop is closed'). This helper drains all pending tasks
before closing the loop, giving httpx a chance to clean up cleanly.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


def run_async(coro):
    """Run an async coroutine from a sync Celery task, draining cleanup tasks first."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
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
            loop.close()
            asyncio.set_event_loop(None)
