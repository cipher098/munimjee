"""Sarvam AI client — Hinglish-tuned chat model used as an alternative
provider for both the bot's thinking call (decide → JSON) and the
customer-facing reply.

Driven by the multi-provider factory in `llm_provider.py`: every call
arrives with an explicit `model` and `max_tokens` chosen by the factory
based on the app default in `agents.yaml` and the seller's
`llm_preferences` override (if any). Nothing about model selection lives
in this file.

Prompt construction is shared with the Claude provider via
`app.bot.prompt_builders`, so the two providers send the SAME prompt + the
SAME context. Sarvam has no prompt caching and no native message roles, so
it sends the whole formatted prompt as the system message and a rendered
transcript (+ latest customer turn) as the user message.

Errors propagate — the factory catches them and falls back to the
provider/model in the agent spec's `fallback_provider` / `fallback_model`.
"""
import logging

import httpx

from app.bot.prompt_builders import (
    build_decide_prompt,
    build_reply_prompt,
    evaluate_interventions,
    render_transcript,
)
from app.config import settings
from app.integrations import llm_logging
from app.integrations._json_utils import LLMOutputParseError, parse_json_relaxed

logger = logging.getLogger(__name__)


def _clean_reply_text(text: str) -> str:
    """Strip artifacts a chat/reasoning model sometimes prepends/wraps: a
    leading speaker label and surrounding quotes. Keeps the reply clean for
    the customer."""
    t = (text or "").strip()
    for prefix in ("Seller:", "seller:", "Reply:", "reply:", "Bot:", "bot:", "Message:", "message:"):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
            break
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ("\"", "'"):
        t = t[1:-1].strip()
    if len(t) >= 2 and t[0] in ("“", "‘") and t[-1] in ("”", "’"):
        t = t[1:-1].strip()
    return t


class SarvamClient:
    """Thin httpx wrapper around Sarvam's OpenAI-compatible chat
    completions endpoint. Model + max_tokens are passed in from the
    factory; no agents.yaml lookup here."""

    def __init__(self) -> None:
        self._api_key = settings.SARVAM_API_KEY
        self._url = settings.SARVAM_API_URL

    async def _chat(self, *, model: str, max_tokens: int, system: str, user: str,
                    temperature: float = 0.7, log_method: str | None = None) -> str:
        if not self._api_key:
            raise RuntimeError("SARVAM_API_KEY not configured")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # Reasoning models burn the budget thinking before they answer —
            # add headroom so the caller's max_tokens still bounds the answer.
            "max_tokens": max_tokens + settings.SARVAM_REASONING_HEADROOM_TOKENS,
            "temperature": temperature,
            "reasoning_effort": settings.SARVAM_REASONING_EFFORT,
        }
        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(timeout=45) as client:
                    response = await client.post(
                        self._url,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                    content = (data["choices"][0]["message"]["content"] or "").strip()
                    usage = data.get("usage") or {}
                    if not content:
                        # Reasoning consumed the whole budget and never emitted
                        # an answer. Treat as a failure so the factory falls back.
                        msg = (
                            f"Sarvam returned empty content "
                            f"(finish_reason={data['choices'][0].get('finish_reason')})"
                        )
                        llm_logging.record(
                            "sarvam", model, log_method,
                            status="error",
                            input_tokens=usage.get("prompt_tokens"),
                            output_tokens=usage.get("completion_tokens"),
                            request=payload, error=msg,
                        )
                        raise LLMOutputParseError(msg)
                    llm_logging.record(
                        "sarvam", model, log_method,
                        input_tokens=usage.get("prompt_tokens"),
                        output_tokens=usage.get("completion_tokens"),
                        request=payload,
                        response=content,
                    )
                    return content
            except (httpx.HTTPError, KeyError, IndexError) as exc:
                last_exc = exc
                logger.warning("Sarvam call attempt %d failed (%s)", attempt, exc)
        assert last_exc is not None
        llm_logging.record(
            "sarvam", model, log_method,
            status="error", request=payload, error=f"{type(last_exc).__name__}: {last_exc}",
        )
        raise last_exc

    async def decide(self, context: dict, *, model: str, max_tokens: int) -> dict:
        """Run the SHARED decide prompt on Sarvam and parse JSON. Raises
        LLMOutputParseError on malformed output so the factory falls back."""
        # Same formatted prompt Claude uses (full CONTEXT section included).
        prompt = await build_decide_prompt(context)
        # Same intervention reminders Claude injects; for Sarvam they go in the
        # user turn since there's no cached/dynamic split.
        reminder_block = evaluate_interventions(context)

        transcript = render_transcript(context.get("message_history"))
        customer_msg = context.get("customer_message") or ""
        parts = []
        if reminder_block:
            parts.append(reminder_block)
        parts.append(f"Recent conversation:\n{transcript}")
        parts.append(f"Latest customer message: {customer_msg!r}")
        parts.append("Choose the next action and return ONLY a JSON object — no prose, no code fences.")
        user_block = "\n\n".join(parts)

        text = await self._chat(
            model=model, max_tokens=max_tokens,
            system=prompt, user=user_block, temperature=0.2,
            log_method="decide",
        )
        return parse_json_relaxed(text)

    async def generate_reply(self, context: dict, *, model: str, max_tokens: int) -> str:
        # Same formatted reply prompt + full context Claude uses.
        prompt = await build_reply_prompt(context)
        transcript = render_transcript(context.get("message_history"))
        customer_msg = context.get("customer_message") or ""
        action = (context.get("decision") or {}).get("action", "")
        user_block = (
            f"Action to take: {action}\n\n"
            f"Recent conversation:\n{transcript}\n\n"
            f"Latest customer message: {customer_msg!r}\n\n"
            "Generate the seller's next message — reply text only, no quotes, no speaker label."
        )
        text = await self._chat(
            model=model, max_tokens=max_tokens,
            system=prompt, user=user_block, temperature=0.7,
            log_method="generate_reply",
        )
        return _clean_reply_text(text)


# ---------------------------------------------------------------------------
# LLMProvider wrapper used by the factory
# ---------------------------------------------------------------------------

from app.integrations.llm_provider import LLMProvider as _LLMProvider  # noqa: E402


class SarvamProvider(_LLMProvider):
    name = "sarvam"

    def __init__(self) -> None:
        self._client = SarvamClient()

    async def decide(self, context: dict, *, model: str, max_tokens: int) -> dict:
        return await self._client.decide(context, model=model, max_tokens=max_tokens)

    async def generate_reply(self, context: dict, *, model: str, max_tokens: int) -> str:
        return await self._client.generate_reply(context, model=model, max_tokens=max_tokens)
