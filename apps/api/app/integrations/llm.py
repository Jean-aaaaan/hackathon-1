"""
Unified LLM client — supports OpenAI (hackathon) and Anthropic (production default).
Agents use structured_call(); chat surfaces use complete_text() / stream_text().
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, AsyncGenerator, Optional

import structlog

from app.config import get_settings

log = structlog.get_logger()


@dataclass
class LLMUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class LLMResponse:
    usage: LLMUsage
    text: str = ""
    structured: Optional[dict] = None


def provider() -> str:
    return get_settings().llm_provider.lower()


def bulk_model() -> str:
    s = get_settings()
    return s.openai_model_bulk if provider() == "openai" else s.anthropic_model_bulk


def quality_model() -> str:
    s = get_settings()
    return s.openai_model_quality if provider() == "openai" else s.anthropic_model_quality


@lru_cache
def _openai_client():
    from openai import AsyncOpenAI

    key = get_settings().openai_api_key
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
    return AsyncOpenAI(api_key=key)


@lru_cache
def _anthropic_client():
    import anthropic

    key = get_settings().anthropic_api_key
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
    return anthropic.AsyncAnthropic(api_key=key)


async def structured_call(
    *,
    system_prompt: str,
    user_message: str,
    tool_name: str,
    tool_schema: dict,
    model: str,
    max_tokens: int = 2048,
    agent_name: str = "agent",
) -> tuple[dict, LLMUsage]:
    """Structured JSON output — Anthropic tool_use or OpenAI function calling."""
    start = time.time()
    if provider() == "openai":
        client = _openai_client()
        response = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            tools=[{
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": f"Output the {tool_name} result",
                    "parameters": tool_schema,
                },
            }],
            tool_choice={"type": "function", "function": {"name": tool_name}},
        )
        usage = LLMUsage(
            input_tokens=response.usage.prompt_tokens or 0,
            output_tokens=response.usage.completion_tokens or 0,
        )
        message = response.choices[0].message
        def _parse_openai_result(resp) -> dict:
            msg = resp.choices[0].message
            if msg.tool_calls:
                raw = msg.tool_calls[0].function.arguments
                r = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(r, dict):
                    raise ValueError(f"OpenAI tool output is not a dict: {type(r).__name__}")
                return r
            # Fallback: parse JSON from content if model skipped tool call
            content = (msg.content or "").strip()
            if content.startswith("```"):
                content = content.split("```", 2)[1]
                if content.startswith("json"):
                    content = content[4:]
            return json.loads(content)

        result = _parse_openai_result(response)

        # GPT-4o-mini occasionally returns {} for complex schemas — retry once
        if not result:
            log.warning(
                "structured_empty_result_retry",
                agent=agent_name, tool=tool_name,
                input_tokens=usage.input_tokens,
            )
            retry_response = await client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                tools=[{
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": f"Output the {tool_name} result",
                        "parameters": tool_schema,
                    },
                }],
                tool_choice={"type": "function", "function": {"name": tool_name}},
            )
            usage = LLMUsage(
                input_tokens=usage.input_tokens + (retry_response.usage.prompt_tokens or 0),
                output_tokens=usage.output_tokens + (retry_response.usage.completion_tokens or 0),
            )
            result = _parse_openai_result(retry_response)
    else:
        client = _anthropic_client()
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
            tools=[{
                "name": tool_name,
                "description": f"Output the {tool_name} result",
                "input_schema": tool_schema,
            }],
            tool_choice={"type": "tool", "name": tool_name},
        )
        usage = LLMUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        result = None
        for block in response.content:
            if block.type == "tool_use":
                result = block.input
                break
        if not isinstance(result, dict):
            raise ValueError("No tool_use block in Anthropic response")

    log.info(
        "llm_call_complete",
        agent=agent_name,
        provider=provider(),
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        latency_ms=round((time.time() - start) * 1000),
    )
    return result, usage


async def complete_text(
    *,
    system_prompt: str,
    user_message: str,
    model: Optional[str] = None,
    max_tokens: int = 2048,
) -> LLMResponse:
    """Non-streaming text completion."""
    model = model or quality_model()
    if provider() == "openai":
        client = _openai_client()
        response = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        text = response.choices[0].message.content or ""
        usage = LLMUsage(
            input_tokens=response.usage.prompt_tokens or 0,
            output_tokens=response.usage.completion_tokens or 0,
        )
    else:
        client = _anthropic_client()
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        text = response.content[0].text
        usage = LLMUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
    return LLMResponse(usage=usage, text=text)


async def stream_text(
    *,
    system_prompt: str,
    messages: list[dict],
    model: Optional[str] = None,
    max_tokens: int = 2000,
) -> AsyncGenerator[tuple[str, Optional[LLMUsage]], None]:
    """
    Stream text chunks. Yields (delta_text, None) then ("", final_usage) at end.
    messages: list of {role, content} user/assistant turns (no system).
    """
    model = model or quality_model()
    if provider() == "openai":
        client = _openai_client()
        stream = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system_prompt}, *messages],
            stream=True,
            stream_options={"include_usage": True},
        )
        usage: Optional[LLMUsage] = None
        async for chunk in stream:
            if chunk.usage:
                usage = LLMUsage(
                    input_tokens=chunk.usage.prompt_tokens or 0,
                    output_tokens=chunk.usage.completion_tokens or 0,
                )
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta, None
        yield "", usage or LLMUsage(0, 0)
    else:
        client = _anthropic_client()
        async with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
        ) as stream_ctx:
            async for text_chunk in stream_ctx.text_stream:
                yield text_chunk, None
            final = await stream_ctx.get_final_message()
            usage = LLMUsage(
                input_tokens=final.usage.input_tokens,
                output_tokens=final.usage.output_tokens,
            )
            yield "", usage