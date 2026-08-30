"""Persist values typed on a page back into the profile — the inverse of flatten.

This powers the "learn silently from page" feature: when a field couldn't be
filled because the profile slot was empty (e.g. a LinkedIn URL the user never
saved), we read the value the user typed — NEVER secrets — and store it, so the
field fills automatically next time.

Every rule is enforced HERE, independent of the caller:

  * Only LEARNABLE single-value keys are written — identity / contact / location
    / links / a few job preferences. Structured or list-shaped data (work,
    education, skills), values derived from another (given/family name from the
    full name), boolean choices, and voluntary EEO demographics are deliberately
    NOT auto-learned.
  * NON-DESTRUCTIVE: only EMPTY profile slots are filled. Existing data is never
    overwritten, so a stray page typo can't clobber good profile data.
  * Light per-kind validation rejects obvious garbage (a URL key must look like a
    URL, an email must contain '@', a phone must have digits, …).
  * SECRET keys can never be written because they simply aren't in LEARNABLE —
    even if a caller mistakenly forwarded one. (The endpoint also refuses SECRET
    fields up front; this is the second layer.)

The write PATH for each key mirrors EXACTLY where flatten.py READS, so the
round-trip holds: learn a value -> the next fill reads it straight back.

Operates on a plain profile dict (the router round-trips it through the Pydantic
model), so this module stays pure/stdlib and unit-testable offline.
"""
import re
from copy import deepcopy
from typing import Any, Dict, List, Tuple

# key -> (path into the profile dict, kind used for validation).
# Paths MUST match flatten.py's read locations or the learn->fill round-trip breaks:
#   links live under job_preferences (flatten prefers those over basics.profiles).
LEARNABLE: Dict[str, Tuple[Tuple[str, ...], str]] = {
    "name":                (("basics", "name"), "text"),
    "email":               (("basics", "email"), "email"),
    "phone":               (("basics", "phone"), "phone"),
    "website":             (("basics", "website"), "url"),
    "headline":            (("basics", "headline"), "text"),
    "summary":             (("basics", "summary"), "text"),
    "address":             (("basics", "location", "address"), "text"),
    "city":                (("basics", "location", "city"), "text"),
    "region":              (("basics", "location", "region"), "text"),
    "postal_code":         (("basics", "location", "postal_code"), "postal_code"),
    "country":             (("basics", "location", "country"), "text"),
    "linkedin":            (("job_preferences", "linkedin"), "url"),
    "github":              (("job_preferences", "github"), "url"),
    "portfolio":           (("job_preferences", "portfolio"), "url"),
    "work_authorization":  (("job_preferences", "work_authorization"), "text"),
    "notice_period":       (("job_preferences", "notice_period"), "text"),
    "earliest_start_date": (("job_preferences", "earliest_start_date"), "text"),
    "work_mode":           (("job_preferences", "work_mode"), "text"),
    "desired_salary":      (("job_preferences", "desired_salary"), "money"),
}

# Keys the resolver can produce that we intentionally DO NOT auto-learn, with the
# reason (surfaced to the caller so the UI can be honest about what it ignored).
NON_LEARNABLE_REASON: Dict[str, str] = {
    "given_name": "derived from full name",
    "family_name": "derived from full name",
    "current_title": "goes in work history (edit profile)",
    "current_company": "goes in work history (edit profile)",
    "education_institution": "goes in education (edit profile)",
    "education_degree": "goes in education (edit profile)",
    "skills": "goes in skills list (edit profile)",
    "requires_sponsorship": "yes/no preference (edit profile)",
    "willing_to_relocate": "yes/no preference (edit profile)",
    "gender": "voluntary EEO — never auto-learned",
    "race_ethnicity": "voluntary EEO — never auto-learned",
    "veteran_status": "voluntary EEO — never auto-learned",
    "disability_status": "voluntary EEO — never auto-learned",
}

MAX_LEN = 2000  # refuse absurdly long paste blobs into a scalar slot


def _valid(kind: str, value: str) -> bool:
    """Light per-kind sanity check so we don't memorize obvious garbage."""
    v = value.strip()
    if not v or len(v) > MAX_LEN:
        return False
    if kind == "email":
        return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v))
    if kind == "url":
        # accept full URLs and bare forms like linkedin.com/in/x — reject spaces
        return (" " not in v) and ("." in v or v.lower().startswith("http"))
    if kind == "phone":
        return sum(c.isdigit() for c in v) >= 6
    if kind == "postal_code":
        return len(v) <= 16
    if kind == "money":
        return any(c.isdigit() for c in v)
    return True  # free text (name/headline/summary/city/…): any non-empty ok


def _get(d: Dict[str, Any], path: Tuple[str, ...]) -> Any:
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _set(d: Dict[str, Any], path: Tuple[str, ...], value: str) -> None:
    cur = d
    for p in path[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[path[-1]] = value


def _is_empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def apply_learned(profile: Dict[str, Any], pairs: List[Dict[str, str]]) -> Dict[str, Any]:
    """Fill empty profile slots from learned page values.

    pairs: [{"key", "value", "label"?}, ...]
    Returns {"profile", "applied": [{key,label,value}], "skipped": [{key,reason}]}.
    The input profile is NOT mutated (a deep copy is returned in "profile").
    """
    out = deepcopy(profile) if isinstance(profile, dict) else {}
    applied: List[Dict[str, str]] = []
    skipped: List[Dict[str, str]] = []
    seen = set()

    for p in pairs or []:
        key = (p.get("key") or "").strip()
        value = (p.get("value") or "").strip()
        label = p.get("label") or key

        if key not in LEARNABLE:
            skipped.append({"key": key, "label": label,
                            "reason": NON_LEARNABLE_REASON.get(key, "not a learnable profile field")})
            continue
        if key in seen:
            skipped.append({"key": key, "label": label, "reason": "duplicate in this batch"})
            continue

        path, kind = LEARNABLE[key]
        if not value:
            skipped.append({"key": key, "label": label, "reason": "empty value"})
            continue
        if not _valid(kind, value):
            skipped.append({"key": key, "label": label, "reason": "doesn't look like a valid " + kind})
            continue
        if not _is_empty(_get(out, path)):
            skipped.append({"key": key, "label": label, "reason": "already set (kept existing)"})
            continue

        _set(out, path, value)
        seen.add(key)
        applied.append({"key": key, "label": label, "value": value})

    return {"profile": out, "applied": applied, "skipped": skipped}
