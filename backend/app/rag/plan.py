"""Build a per-field fill plan for a perceived form.

Order of resolution for every field:
  1. Authoritative sensitivity classify (never trusts the extension's flags).
     SECRET  -> action "manual_entry": value None, never resolved, never sent.
  2. Deterministic resolver (autocomplete + labels). A hit -> action "fill".
  3. Leftover SAFE/PII fields -> optional LLM matcher, which picks a profile KEY
     (never a value). A hit -> action "fill" (value pulled locally by key).
  4. Still nothing: SAFE free-text -> action "generate" (Phase 5 writes it);
     everything else -> action "unmapped".

`matcher` is injected (default None = deterministic-only) so this orchestrator is
fully unit-testable offline. When wired in production it is rag.mapper.llm_match.

Pure/stdlib except for the injected matcher — importable and testable without the
web stack.
"""
from typing import Any, Callable, Dict, List, Optional

from ..privacy.classifier import Sensitivity, classify_field
from .flatten import facts_by_key, flatten_profile, key_catalog
from .resolver import match_option, resolve_field

Matcher = Callable[[List[Dict[str, Any]], List[Dict[str, str]]], Dict[str, Optional[str]]]

_MAX_OPTIONS_TO_LLM = 15


def _ftype(field: Any) -> str:
    return (getattr(field, "type", "") or "").lower()


def _is_free_text(field: Any) -> bool:
    ft = _ftype(field)
    if ft == "textarea":
        return True
    return ft in ("text", "") and not (getattr(field, "options", None) or [])


def _base(field: Any, sens: Sensitivity) -> Dict[str, Any]:
    return {
        "field_id": getattr(field, "field_id", None),
        "selector": getattr(field, "selector", None),  # for the extension to re-find the element
        "label": getattr(field, "label", None) or getattr(field, "name", None),
        "type": _ftype(field),
        "sensitivity": sens.value,
    }


def _rec(base: Dict[str, Any], action: str, value=None, source_key=None,
         confidence=0.0, via="none", reason=None) -> Dict[str, Any]:
    return {**base, "action": action, "value": value, "source_key": source_key,
            "confidence": round(confidence, 2), "via": via, "reason": reason}


def _field_payload(field: Any) -> Dict[str, Any]:
    """What the LLM matcher sees for one field: label/type/option-labels only.
    Contains page content, never any value from the user's profile."""
    opts = getattr(field, "options", None) or []
    labels = []
    for o in opts[:_MAX_OPTIONS_TO_LLM]:
        lab = o.get("label") if isinstance(o, dict) else getattr(o, "label", None)
        if lab:
            labels.append(str(lab))
    return {
        "field_id": getattr(field, "field_id", None),
        "label": getattr(field, "label", None) or getattr(field, "name", None) or "",
        "type": _ftype(field),
        "options": labels,
    }


def _fill_from_key(field: Any, key: str, fbk: Dict[str, Dict[str, str]],
                   base: Dict[str, Any], via: str, confidence: float) -> Dict[str, Any]:
    fact = fbk[key]
    value = fact["value"]
    if _ftype(field) in ("select", "radio") and (getattr(field, "options", None) or []):
        opt = match_option(value, getattr(field, "options"))
        if opt is None:
            return _rec(base, "unmapped", source_key=key, confidence=0.3, via=via,
                        reason="no matching option")
        value = opt
    return _rec(base, "fill", value=value, source_key=key, confidence=confidence,
                via=via, reason=fact["kind"])


def _finalize_leftover(field: Any, key: Optional[str], fbk: Dict[str, Dict[str, str]],
                       base: Dict[str, Any]) -> Dict[str, Any]:
    if key and key in fbk:
        return _fill_from_key(field, key, fbk, base, via="llm", confidence=0.65)
    # No mapping. SAFE free-text is deferred to generation; PII is never generated.
    if base["sensitivity"] == Sensitivity.SAFE.value and _is_free_text(field):
        return _rec(base, "generate", via="none", reason="free-text answer (Phase 5)")
    return _rec(base, "unmapped", via="none", reason="no profile match")


def build_plan(form: Any, profile: Any, matcher: Optional[Matcher] = None) -> Dict[str, Any]:
    facts = flatten_profile(profile)
    fbk = facts_by_key(facts)
    fields = list(getattr(form, "fields", None) or [])

    records: Dict[Any, Dict[str, Any]] = {}
    leftovers: List[Any] = []

    for f in fields:
        sens, sreason = classify_field(f)
        base = _base(f, sens)
        fid = base["field_id"]

        if sens is Sensitivity.SECRET:
            # Hard rule: never resolved, never valued, never sent anywhere.
            records[fid] = _rec(base, "manual_entry", confidence=1.0,
                                reason=sreason or "secret")
            continue

        m = resolve_field(f, fbk)
        if m and m["value"] is not None:
            records[fid] = _rec(base, "fill", value=m["value"], source_key=m["key"],
                                confidence=m["confidence"], via="deterministic",
                                reason=m["reason"])
        elif m and m["value"] is None:
            records[fid] = _rec(base, "unmapped", source_key=m["key"], confidence=0.3,
                                via="deterministic", reason=m["reason"])
        else:
            leftovers.append(f)  # decide after the (optional) LLM pass

    matches: Dict[str, Optional[str]] = {}
    if matcher and leftovers:
        payload = [_field_payload(f) for f in leftovers]
        catalog = key_catalog(facts)  # keys + hints only — never values
        try:
            matches = matcher(payload, catalog) or {}
        except Exception:
            matches = {}  # a matcher failure degrades gracefully to deterministic-only

    valid_keys = set(fbk.keys())
    for f in leftovers:
        fid = getattr(f, "field_id", None)
        key = matches.get(fid)
        if key not in valid_keys:  # ignore hallucinated / null keys
            key = None
        records[fid] = _finalize_leftover(f, key, fbk, _base(f, classify_field(f)[0]))

    ordered = [records[getattr(f, "field_id", None)] for f in fields]
    summary = {"fill": 0, "manual_entry": 0, "generate": 0, "unmapped": 0}
    for r in ordered:
        summary[r["action"]] = summary.get(r["action"], 0) + 1
    summary["total"] = len(ordered)

    return {
        "ok": True,
        "url": getattr(form, "url", None),
        "used_llm": bool(matcher and leftovers),
        "summary": summary,
        "fields": ordered,
    }
