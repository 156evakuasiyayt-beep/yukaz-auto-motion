"""Provider-neutral structured LLM calls (Anthropic or OpenAI) with usage/cost tracking.

Provider (env LLM_PROVIDER = anthropic | openai; default: whichever key is set, Anthropic first):
  anthropic → ANTHROPIC_API_KEY, model CLAUDE_MODEL (default claude-opus-5-5)
  openai    → OPENAI_API_KEY,    model OPENAI_MODEL (default gpt-6.1-sol)
OpenAI calls use the Flex tier (50% cheaper, slower) unless OPENAI_FLEX=0; if Flex is
unavailable the call is retried once on the default tier.
"""
import base64
import logging
import os
from pathlib import Path
from typing import TypeVar

import anthropic
import openai
from pydantic import BaseModel

log = logging.getLogger("autopost.llm")
T = TypeVar("T", bound=BaseModel)

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL") or "claude-opus-5-5"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL") or "gpt-6.1-sol"
OPENAI_FLEX = (os.environ.get("OPENAI_FLEX") or "1") != "0"

# USD per 1M tokens: (input, cached input, output) — standard tier.
# Source: developers.openai.com/api/docs/pricing and the Anthropic model table (2026-10).
PRICES = {
    "gpt-6.1-sol": (2.00, 0.10, 10.00),
    "gpt-6-sol": (2.00, 0.20, 10.00),
    "gpt-5.5": (5.00, 0.50, 30.00),
    "gpt-5.4": (2.50, 0.25, 15.00),
    "gpt-5.4-mini": (0.75, 0.075, 4.50),
    "claude-opus-5-5": (4.00, 0.20, 20.00),
}
FLEX_DISCOUNT = 0.5

USAGE: list[dict] = []  # one entry per successful call, for the daily cost report


def provider() -> str | None:
    choice = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if choice in ("anthropic", "openai"):
        return choice
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


def model_name() -> str | None:
    p = provider()
    return CLAUDE_MODEL if p == "anthropic" else OPENAI_MODEL if p == "openai" else None


def _record(model, tier, inp, cached, out, label):
    price = PRICES.get(model)
    cost = None
    if price:
        cost = ((inp - cached) * price[0] + cached * price[1] + out * price[2]) / 1e6
        if tier == "flex":
            cost *= FLEX_DISCOUNT
    USAGE.append({"label": label, "model": model, "tier": tier, "input": inp, "cached": cached,
                  "output": out, "cost_usd": cost})
    log.info("LLM %s [%s/%s]: in %d (cached %d) · out %d · $%s", label, model, tier, inp, cached, out,
             f"{cost:.4f}" if cost is not None else "?")


def usage_summary() -> dict:
    known = [u["cost_usd"] for u in USAGE if u["cost_usd"] is not None]
    return {
        "calls": len(USAGE),
        "input_tokens": sum(u["input"] for u in USAGE),
        "output_tokens": sum(u["output"] for u in USAGE),
        "cost_usd": round(sum(known), 4) if known else None,
        "by_call": [(u["label"], u["output"], None if u["cost_usd"] is None else round(u["cost_usd"], 4)) for u in USAGE],
    }


def _openai_call(system, content, schema, max_tokens, tier):
    kwargs = {"service_tier": tier} if tier == "flex" else {}
    return openai.OpenAI(timeout=900, max_retries=1).chat.completions.parse(
        model=OPENAI_MODEL, max_completion_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
        response_format=schema, **kwargs)


def structured(system: str, text: str, schema: type[T], *, images: list[Path] | None = None,
               max_tokens: int = 16000, label: str = "call") -> T | None:
    """One request → validated pydantic object, or None on any failure/refusal."""
    p = provider()
    if p is None:
        log.warning("no LLM key set (ANTHROPIC_API_KEY / OPENAI_API_KEY)")
        return None
    images = images or []
    try:
        if p == "anthropic":
            content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                     "data": base64.b64encode(i.read_bytes()).decode()}}
                       for i in images] + [{"type": "text", "text": text}]
            resp = anthropic.Anthropic(timeout=900).messages.parse(
                model=CLAUDE_MODEL, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": content}], output_format=schema)
            u = resp.usage
            _record(CLAUDE_MODEL, "standard", u.input_tokens + (u.cache_read_input_tokens or 0),
                    u.cache_read_input_tokens or 0, u.output_tokens, label)
            if resp.stop_reason in ("refusal", "max_tokens") or resp.parsed_output is None:
                log.error("Claude: no usable output (stop_reason=%s)", resp.stop_reason)
                return None
            return resp.parsed_output

        content = [{"type": "image_url", "image_url": {
                       "url": "data:image/jpeg;base64," + base64.b64encode(i.read_bytes()).decode()}}
                   for i in images] + [{"type": "text", "text": text}]
        tier = "flex" if OPENAI_FLEX else "default"
        try:
            comp = _openai_call(system, content, schema, max_tokens * 2, tier)
        except (openai.RateLimitError, openai.APITimeoutError, openai.InternalServerError) as e:
            if tier != "flex":
                raise
            log.warning("Flex tier unavailable (%s) — retrying on the default tier", type(e).__name__)
            tier = "default"
            comp = _openai_call(system, content, schema, max_tokens * 2, tier)
        u = comp.usage
        if u:
            cached = (u.prompt_tokens_details.cached_tokens if u.prompt_tokens_details else 0) or 0
            _record(OPENAI_MODEL, tier, u.prompt_tokens, cached, u.completion_tokens, label)
        msg = comp.choices[0].message
        if msg.refusal or msg.parsed is None:
            log.error("OpenAI: no usable output (refusal=%s, finish=%s)", msg.refusal, comp.choices[0].finish_reason)
            return None
        return msg.parsed
    except (anthropic.APIStatusError, openai.APIStatusError) as e:
        log.error("%s API error %s: %s", p, getattr(e, "status_code", "?"), getattr(e, "message", e))
    except (anthropic.APIConnectionError, openai.APIConnectionError) as e:
        log.error("%s connection error: %s", p, e)
    except Exception as e:  # schema validation errors, length-limit parse errors, …
        log.error("%s structured call failed: %s", p, e)
    return None
