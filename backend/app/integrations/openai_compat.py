"""Generic OpenAI-compatible chat provider.

Many vendors (Google Gemini, OpenAI, DeepSeek, DeepInfra, Groq, …) expose the
same `POST {base_url}/chat/completions` shape. This one client serves all of
them — instantiate per vendor with its base_url + api_key and register under a
provider name in `llm_provider.py`. Currently used for "gemini".

Prompt construction is the SHARED `app.bot.prompt_builders`, so any provider
wired here automatically gets the exact same prompt + context as Claude and
Sarvam (the parity work). Errors propagate so the factory falls back to the
agent spec's fallback_provider/fallback_model.
"""
import logging

import httpx

from app.bot.prompt_builders import (
    build_decide_prompt,
    build_reply_prompt,
    evaluate_interventions,
    render_transcript,
)
from app.integrations import llm_logging
from app.integrations._json_utils import LLMOutputParseError, parse_json_relaxed
from app.integrations.llm_provider import LLMProvider
from app.integrations.sarvam import _clean_reply_text

logger = logging.getLogger(__name__)


class OpenAICompatClient:
    """Thin httpx wrapper around an OpenAI-compatible chat completions endpoint."""

    def __init__(self, name: str, base_url: str, api_key: str) -> None:
        self.name = name
        # Accept base_url with or without a trailing /chat/completions.
        base = (base_url or "").rstrip("/")
        self._url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        self._api_key = api_key

    async def _chat(self, *, model: str, max_tokens: int, system: str, user: str,
                    temperature: float = 0.7, log_method: str | None = None) -> str:
        messages = [{"role": "user", "content": user}]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        return await self._post(
            model=model, max_tokens=max_tokens, messages=messages,
            temperature=temperature, log_method=log_method,
        )

    async def _chat_vision(self, *, model: str, max_tokens: int, prompt: str,
                           image_url: str, temperature: float = 0.2,
                           log_method: str | None = None) -> str:
        """OpenAI-compatible vision call — image as a (possibly data:) URL."""
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }]
        return await self._post(
            model=model, max_tokens=max_tokens, messages=messages,
            temperature=temperature, log_method=log_method,
        )

    async def _post(self, *, model: str, max_tokens: int, messages: list,
                    temperature: float = 0.7, log_method: str | None = None) -> str:
        if not self._api_key:
            raise RuntimeError(f"{self.name.upper()}_API_KEY not configured")
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
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
                        msg = (
                            f"{self.name} returned empty content "
                            f"(finish_reason={data['choices'][0].get('finish_reason')})"
                        )
                        llm_logging.record(
                            self.name, model, log_method, status="error",
                            input_tokens=usage.get("prompt_tokens"),
                            output_tokens=usage.get("completion_tokens"),
                            request=payload, error=msg,
                        )
                        raise LLMOutputParseError(msg)
                    llm_logging.record(
                        self.name, model, log_method,
                        input_tokens=usage.get("prompt_tokens"),
                        output_tokens=usage.get("completion_tokens"),
                        request=payload, response=content,
                    )
                    return content
            except (httpx.HTTPError, KeyError, IndexError) as exc:
                last_exc = exc
                logger.warning("%s call attempt %d failed (%s)", self.name, attempt, exc)
        assert last_exc is not None
        llm_logging.record(
            self.name, model, log_method,
            status="error", request=payload, error=f"{type(last_exc).__name__}: {last_exc}",
        )
        raise last_exc

    async def decide(self, context: dict, *, model: str, max_tokens: int) -> dict:
        prompt = await build_decide_prompt(context)
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
            system=prompt, user=user_block, temperature=0.2, log_method="decide",
        )
        return parse_json_relaxed(text)

    async def generate_reply(self, context: dict, *, model: str, max_tokens: int) -> str:
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
            system=prompt, user=user_block, temperature=0.7, log_method="generate_reply",
        )
        return _clean_reply_text(text)


class OpenAICompatProvider(LLMProvider):
    def __init__(self, name: str, base_url: str, api_key: str) -> None:
        self.name = name
        self._client = OpenAICompatClient(name, base_url, api_key)

    async def decide(self, context: dict, *, model: str, max_tokens: int) -> dict:
        return await self._client.decide(context, model=model, max_tokens=max_tokens)

    async def generate_reply(self, context: dict, *, model: str, max_tokens: int) -> str:
        return await self._client.generate_reply(context, model=model, max_tokens=max_tokens)

    async def complete_text(self, *, system: str, user: str, model: str,
                            max_tokens: int, log_method: str | None = None) -> str:
        return await self._client._chat(
            model=model, max_tokens=max_tokens, system=system, user=user,
            temperature=0.3, log_method=log_method,
        )

    async def complete_vision(self, *, prompt: str, image: dict, model: str,
                              max_tokens: int, log_method: str | None = None) -> str:
        if image.get("kind") == "base64":
            image_url = f"data:{image['media_type']};base64,{image['data']}"
        else:
            image_url = image["url"]
        return await self._client._chat_vision(
            model=model, max_tokens=max_tokens, prompt=prompt, image_url=image_url,
            log_method=log_method,
        )
