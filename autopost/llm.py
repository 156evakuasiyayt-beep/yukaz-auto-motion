"""Provider-neutral structured LLM calls (Anthropic or OpenAI).

Provider (env LLM_PROVIDER = anthropic | openai; default: whichever key is set, Anthropic first):
  anthropic → ANTHROPIC_API_KEY, model CLAUDE_MODEL (default claude-opus-5-5)
  openai    → OPENAI_API_KEY,    model OPENAI_MODEL (default gpt-5.5)
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
OPENAI_MODEL = os.environ.get("OPENAI_MODEL") or "gpt-5.5"


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


def structured(system: str, text: str, schema: type[T], *, images: list[Path] | None = None,
               max_tokens: int = 16000) -> T | None:
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
            if resp.stop_reason in ("refusal", "max_tokens") or resp.parsed_output is None:
                log.error("Claude: no usable output (stop_reason=%s)", resp.stop_reason)
                return None
            return resp.parsed_output

        content = [{"type": "image_url", "image_url": {
                       "url": "data:image/jpeg;base64," + base64.b64encode(i.read_bytes()).decode()}}
                   for i in images] + [{"type": "text", "text": text}]
        comp = openai.OpenAI(timeout=900).chat.completions.parse(
            model=OPENAI_MODEL, max_completion_tokens=max_tokens * 2,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
            response_format=schema)
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
