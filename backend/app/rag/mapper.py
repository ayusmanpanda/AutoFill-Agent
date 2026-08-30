"""LLM fallback matcher: match leftover form fields to profile KEYS.

Called only for SAFE/PII fields the deterministic resolver could not map. The
model is shown the fields (label/type/option-labels — page content) and a catalog
of profile *keys* with short hints. It never sees a single profile value: it just
picks which key answers each field, and the actual value is pulled locally by key
in the orchestrator. The call still routes through safe_completion (the single
cloud choke point) so the privacy guarantee stays structural even here.

Returns {field_id: key} keeping only catalog keys for known field ids; anything
null / hallucinated is dropped, which the orchestrator treats as "no match".
"""
import json
import re
from typing import Any, Dict, List, Optional

from ..privacy.guard import safe_completion

_SYSTEM = (
    "You map web form fields to keys in a person's stored profile. "
    "You are given a list of form fields and a catalog of available profile keys. "
    "For each field, choose the single profile key that best answers it, or null "
    "if no key fits (e.g. a free-text question that needs a written answer). "
    "Only use keys that appear in the catalog. "
    'Respond with ONLY a JSON object shaped like '
    '{"matches": {"<field_id>": "<key or null>"}} and nothing else.'
)

_JSON_OBJ = re.compile(r"\{.*\}", re.S)


def _parse(raw: str, valid_field_ids: set, valid_keys: set) -> Dict[str, str]:
    if not raw:
        return {}
    m = _JSON_OBJ.search(raw)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {}
    matches = data.get("matches", data) if isinstance(data, dict) else {}
    if not isinstance(matches, dict):
        return {}
    out: Dict[str, str] = {}
    for fid, key in matches.items():
        if fid in valid_field_ids and isinstance(key, str) and key in valid_keys:
            out[fid] = key
    return out


def llm_match(fields: List[Dict[str, Any]], catalog: List[Dict[str, str]],
              max_tokens: int = 400) -> Dict[str, str]:
    if not fields or not catalog:
        return {}
    valid_field_ids = {f.get("field_id") for f in fields}
    valid_keys = {c.get("key") for c in catalog}
    user = json.dumps({"fields": fields, "profile_keys": catalog}, ensure_ascii=False)
    out = safe_completion(
        [{"role": "system", "content": _SYSTEM},
         {"role": "user", "content": user}],
        max_tokens=max_tokens,
    )
    return _parse(out.get("reply", ""), valid_field_ids, valid_keys)
