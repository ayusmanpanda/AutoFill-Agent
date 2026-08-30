"""Deterministic field -> profile-fact resolver. NO LLM, NO network.

Given a perceived field and the flattened profile facts (by key), pick the fact
that should fill the field, using the field's `autocomplete` token first (the
most reliable signal), then a label/name/placeholder regex. For select/radio
fields the resolved value is matched against the field's own options.

This path handles the bulk of a job application's identity/contact/location
fields with zero egress and zero cost. SECRET fields are never passed here — the
orchestrator excludes them before calling.

Pure/stdlib — importable and testable without the web stack.
"""
import re
from typing import Any, Dict, List, Optional

# autocomplete token -> profile fact key (SECRET tokens like cc-* are excluded upstream)
_AC_KEY = {
    "email": "email",
    "tel": "phone", "tel-national": "phone", "tel-local": "phone",
    "name": "name", "given-name": "given_name", "family-name": "family_name",
    "organization": "current_company", "organization-title": "current_title",
    "street-address": "address", "address-line1": "address",
    "address-level2": "city", "address-level1": "region",
    "postal-code": "postal_code", "country": "country", "country-name": "country",
    "url": "website",
}

# Ordered label/name rules — first match wins, so specific rules precede generic.
_LABEL_RULES = [
    (re.compile(r"e-?mail", re.I), "email"),
    (re.compile(r"linked ?in", re.I), "linkedin"),
    (re.compile(r"git ?hub", re.I), "github"),
    (re.compile(r"portfolio", re.I), "portfolio"),
    (re.compile(r"personal (web ?site|url)|home ?page|^web ?site$", re.I), "website"),
    (re.compile(r"phone|mobile|telephone|\btel\b|contact number", re.I), "phone"),
    (re.compile(r"first ?name|given ?name|fore ?name", re.I), "given_name"),
    (re.compile(r"last ?name|sur ?name|family ?name", re.I), "family_name"),
    (re.compile(r"full ?name|legal name|your name|^name$", re.I), "name"),
    (re.compile(r"street|address ?line|mailing|\baddress\b", re.I), "address"),
    (re.compile(r"\bcity\b|town|locality", re.I), "city"),
    (re.compile(r"\bstate\b|province|region", re.I), "region"),
    (re.compile(r"\bzip\b|postal|pin ?code|post ?code", re.I), "postal_code"),
    (re.compile(r"country|nationality|nation", re.I), "country"),
    (re.compile(r"current (employer|company)|employer|company|organization", re.I), "current_company"),
    (re.compile(r"current (title|role|position)|job title|\btitle\b|position|role", re.I), "current_title"),
    (re.compile(r"head ?line", re.I), "headline"),
    (re.compile(r"school|university|college|institution|alma ?mater", re.I), "education_institution"),
    (re.compile(r"degree|qualification|field of study|\bmajor\b", re.I), "education_degree"),
    (re.compile(r"skills?|technolog|proficien", re.I), "skills"),
    (re.compile(r"work authoriz|right to work|authoriz(ed|ation) to work|visa status", re.I), "work_authorization"),
    (re.compile(r"sponsor", re.I), "requires_sponsorship"),
    (re.compile(r"relocat", re.I), "willing_to_relocate"),
    (re.compile(r"salary|compensation|expected pay|\bctc\b", re.I), "desired_salary"),
    (re.compile(r"notice ?period", re.I), "notice_period"),
    (re.compile(r"start date|availabilit|earliest.*start", re.I), "earliest_start_date"),
    (re.compile(r"work mode|remote|hybrid|on ?site", re.I), "work_mode"),
    (re.compile(r"gender", re.I), "gender"),
    (re.compile(r"race|ethnic", re.I), "race_ethnicity"),
    (re.compile(r"veteran", re.I), "veteran_status"),
    (re.compile(r"disab", re.I), "disability_status"),
]

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _norm_hay(*parts: Optional[str]) -> str:
    raw = " ".join(p for p in parts if p)
    return _CAMEL.sub(" ", raw).replace("_", " ")


def _norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (s or "").lower())).strip()


def _opt(o: Any, attr: str) -> str:
    v = o.get(attr) if isinstance(o, dict) else getattr(o, attr, None)
    return "" if v is None else str(v)


def match_option(desired: str, options: List[Any]) -> Optional[str]:
    """Pick the option whose label/value best matches `desired`; return the
    option's value (what a <select> needs), or its label if value is empty.
    Returns None if nothing reasonably matches."""
    d = _norm(desired)
    if not d:
        return None
    best = None
    best_score = 0
    for o in options:
        label = _norm(_opt(o, "label"))
        value = _norm(_opt(o, "value"))
        for cand in (label, value):
            if not cand:
                continue
            if cand == d:
                score = 3
            elif d in cand.split() or cand in d.split():
                score = 2
            elif d in cand or cand in d:
                score = 1
            else:
                score = 0
            if score > best_score:
                best_score = score
                best = o
    if best is None or best_score < 1:
        return None
    return _opt(best, "value") or _opt(best, "label")


def _key_from_autocomplete(ac: str) -> Optional[str]:
    ac = (ac or "").lower().strip()
    if not ac:
        return None
    # autocomplete may be space-separated sections e.g. "shipping postal-code"
    for tok in ac.split():
        if tok in _AC_KEY:
            return _AC_KEY[tok]
    return _AC_KEY.get(ac)


def _key_from_text(hay: str) -> Optional[str]:
    for rx, key in _LABEL_RULES:
        if rx.search(hay):
            return key
    return None


def key_for_field(field: Any) -> Optional[str]:
    """Resolve a field to a profile KEY using the same signals as resolve_field
    (autocomplete token first, then label/name/placeholder/group regex) but
    WITHOUT requiring the profile to already hold a value for that key.

    resolve_field is for FILLING, so it returns None whenever the key isn't in
    the flattened facts (empty slots are dropped by flatten). The 'learn' path
    needs the key precisely when the slot IS empty — that's the field we want to
    capture — so it uses this value-independent resolver instead."""
    ac = getattr(field, "autocomplete", None)
    key = _key_from_autocomplete(ac)
    if key:
        return key
    hay = _norm_hay(
        getattr(field, "label", None),
        getattr(field, "name", None),
        getattr(field, "placeholder", None),
        getattr(field, "group", None),
    )
    return _key_from_text(hay)


def resolve_field(field: Any, facts_by_key: Dict[str, Dict[str, str]]) -> Optional[Dict[str, Any]]:
    """Return {key, value, confidence, reason, via} or None if no confident
    deterministic mapping exists. value is None when we know the key but the
    field is a select/radio with no matching option."""
    key = key_for_field(field)
    if not key or key not in facts_by_key:
        return None
    # An autocomplete-token hit is more reliable than a label/name regex hit.
    confidence = 0.9 if _key_from_autocomplete(getattr(field, "autocomplete", None)) == key else 0.75

    fact = facts_by_key[key]
    value = fact["value"]
    ftype = (getattr(field, "type", "") or "").lower()
    options = getattr(field, "options", None) or []
    if ftype in ("select", "radio") and options:
        opt = match_option(value, options)
        if opt is None:
            return {"key": key, "value": None, "confidence": 0.3,
                    "reason": "no matching option", "via": "deterministic"}
        value = opt
    return {"key": key, "value": value, "confidence": confidence,
            "reason": fact["kind"], "via": "deterministic"}
