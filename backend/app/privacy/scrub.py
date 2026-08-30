"""Egress scrub: redact PII from any text before it goes to the cloud LLM, then
re-hydrate the model's reply locally.

Secret *values* never reach this layer (they are never stored), so this is PII
defense-in-depth. A Scrubber is stateful for the lifetime of one request: the
same value always maps to the same placeholder, and the placeholder->original
map stays on the machine — it is never sent anywhere.

Pure/stdlib only.
"""
import re
from typing import List, Optional, Tuple

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s()\-]{7,}\d(?!\w)")
_LONGNUM = re.compile(r"\b\d{9,}\b")

# Applied in order AFTER exact known-value substitution.
_PATTERNS = [
    (_EMAIL, "EMAIL"),
    (_SSN, "SSN"),
    (_CARD, "CARD"),
    (_PHONE, "PHONE"),
    (_LONGNUM, "NUM"),
]


class Scrubber:
    def __init__(self, known: Optional[List[Tuple[str, str]]] = None):
        # known: exact (value, KIND) strings from the profile; skip very short
        # ones to avoid over-scrubbing common substrings.
        self.known = [(v, k) for (v, k) in (known or []) if v and len(v) >= 4]
        # longest first so full strings are replaced before their substrings.
        self.known.sort(key=lambda vk: len(vk[0]), reverse=True)
        self._map = {}
        self._rev = {}
        self._counters = {}

    def _placeholder(self, kind: str, original: str) -> str:
        if original in self._rev:
            return self._rev[original]
        n = self._counters.get(kind, 0) + 1
        self._counters[kind] = n
        ph = "[[%s_%d]]" % (kind, n)
        self._map[ph] = original
        self._rev[original] = ph
        return ph

    def scrub(self, text):
        if not text:
            return text
        s = str(text)
        # 1) exact known profile values, bounded so we don't match inside words
        for value, kind in self.known:
            pat = r"(?<!\w)" + re.escape(value) + r"(?!\w)"
            s = re.sub(pat, lambda m, k=kind, o=value: self._placeholder(k, o),
                       s, flags=re.IGNORECASE)
        # 2) format-based detectors
        for rx, kind in _PATTERNS:
            s = rx.sub(lambda m, k=kind: self._placeholder(k, m.group(0)), s)
        return s

    def rehydrate(self, text):
        if not text:
            return text
        s = str(text)
        for ph, original in self._map.items():
            s = s.replace(ph, original)
        return s

    @property
    def count(self) -> int:
        return len(self._map)

    @property
    def type_counts(self) -> dict:
        return dict(self._counters)


def build_scrubber_from_profile(profile) -> "Scrubber":
    """Collect exact PII values from a Profile (duck-typed) as known values."""
    known: List[Tuple[str, str]] = []
    basics = getattr(profile, "basics", None)
    if basics is not None:
        for attr, kind in (("email", "EMAIL"), ("phone", "PHONE"),
                           ("website", "URL"), ("name", "NAME")):
            v = getattr(basics, attr, None)
            if v:
                known.append((str(v), kind))
        name = getattr(basics, "name", None)
        if name:
            for part in str(name).split():
                if len(part) >= 3:
                    known.append((part, "NAME"))
        loc = getattr(basics, "location", None)
        if loc is not None:
            for attr in ("address", "city", "region", "postal_code", "country"):
                v = getattr(loc, attr, None)
                if v:
                    known.append((str(v), "ADDR"))
    jp = getattr(profile, "job_preferences", None)
    if jp is not None:
        for attr in ("linkedin", "github", "portfolio"):
            v = getattr(jp, attr, None)
            if v:
                known.append((str(v), "URL"))
    return Scrubber(known)
