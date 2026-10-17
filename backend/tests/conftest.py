"""Shared pytest fixtures: isolated configuration, no outbound sends, replay only."""
import pathlib
import tempfile

from tests.safety import install_test_safety

# Must run before application imports during test collection, not in a fixture.
install_test_safety()

# Imported application modules capture UPLOAD_DIR at import time. Give this
# pytest invocation its own directory before collection can import those modules.
from app import paths

_uploads = tempfile.TemporaryDirectory(prefix="munimjee-test-uploads-")
paths.UPLOAD_DIR = pathlib.Path(_uploads.name)

import pytest
import vcr

from tests.conftest_db import migrated_engine  # noqa: F401; shared fixture dependency

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"


def pytest_sessionfinish(session, exitstatus):
    _uploads.cleanup()


@pytest.fixture
def claude_cassette():
    """Returns a context manager that strictly replays a Claude API call.

    Usage:
        async def test_x(claude_cassette):
            with claude_cassette("decide_basic"):
                result = await ClaudeClient().decide({...})
    """
    def _open(name: str):
        return vcr.use_cassette(
            str(CASSETTE_DIR / f"{name}.yaml"),
            record_mode="none",
            # Strip credentials before persisting to disk.
            filter_headers=[
                ("x-api-key", "REDACTED"),
                ("anthropic-api-key", "REDACTED"),
                ("authorization", "REDACTED"),
            ],
            # Match by URL + body so different prompts route to different cassettes.
            match_on=["method", "scheme", "host", "port", "path", "query", "body"],
            decode_compressed_response=True,
        )

    return _open
