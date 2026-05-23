"""Shared pytest fixtures.

VCR is used to record real Anthropic responses once, then replay them
in CI without an API key. To record, set:
    VCR_RECORD=1 ANTHROPIC_API_KEY=sk-... pytest backend/tests -v
To replay (default, no API key needed):
    pytest backend/tests -v
"""
import os
import pathlib

import pytest
import vcr

# Provide a placeholder API key so anthropic.AsyncAnthropic(api_key=...) does
# not crash at construction time during replay. Real key is only needed when
# VCR_RECORD=1.
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-replay-only-not-a-real-key")

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"


@pytest.fixture
def claude_cassette():
    """Returns a context manager that records or replays a Claude API call.

    Usage:
        async def test_x(claude_cassette):
            with claude_cassette("decide_basic"):
                result = await ClaudeClient().decide({...})
    """
    record_mode = "all" if os.environ.get("VCR_RECORD") == "1" else "none"

    def _open(name: str):
        return vcr.use_cassette(
            str(CASSETTE_DIR / f"{name}.yaml"),
            record_mode=record_mode,
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
