"""The single choke point for cloud LLM calls.

Everything that talks to the cloud model goes through safe_completion(): it
scrubs PII out of the outgoing messages, calls the model, then re-hydrates the
reply locally. Routing all calls through here makes the privacy guarantee
structural instead of relying on per-call discipline.
"""
from typing import Dict, List

import litellm

from ..config import settings
from ..profile import store
from .scrub import build_scrubber_from_profile


def safe_completion(messages: List[Dict], max_tokens: int = 300) -> dict:
    scrubber = build_scrubber_from_profile(store.get_profile())
    scrubbed = [dict(m, content=scrubber.scrub(m.get("content", ""))) for m in messages]

    resp = litellm.completion(
        model=settings.LLM_MODEL,
        custom_llm_provider=settings.LLM_PROVIDER,
        messages=scrubbed,
        max_tokens=max_tokens,
    )
    raw = resp["choices"][0]["message"]["content"]
    return {
        "reply": scrubber.rehydrate(raw),
        "redactions": scrubber.count,
        "redaction_types": scrubber.type_counts,
    }
