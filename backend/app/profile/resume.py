"""Resume import — turn an uploaded resume into profile fields, locally.

Privacy-first and free: the DEFAULT path is 100% local and deterministic — we
extract the resume's text (pypdf for PDF, plain decode for .txt) and pull out the
obvious contact fields with regex (email, phone, LinkedIn, GitHub, portfolio, and
a best-guess name). No network, no LLM, no cost. Optional LLM enrichment can be
layered on later behind the same `safe_completion` scrub choke point.

Only the deterministic text→facts extraction lives here (pypdf + stdlib), so it is
importable and unit-testable in the sandbox without the web stack. Mapping the
extracted facts into the profile reuses `rag.learn.apply_learned`, so the same
"fill empty slots only, never overwrite" rule applies.
"""
import io
import re
from typing import Dict, List, Optional

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Phones: keep it conservative to avoid grabbing years/IDs. 7-15 digits with
# common separators, optional leading +.
_PHONE = re.compile(r"(?<!\d)(\+?\d[\d\s().\-]{7,16}\d)(?!\d)")
_LINKEDIN = re.compile(r"(?:https?://)?(?:[\w.]+\.)?linkedin\.com/in/[A-Za-z0-9\-_%/]+", re.I)
_GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9\-_]+", re.I)
_URL = re.compile(r"https?://[^\s)>\]]+", re.I)

_LABELISH = re.compile(r"(resume|curriculum|vitae|cv|profile|summary|objective)", re.I)


def extract_text(data: bytes, filename: str = "") -> str:
    """Best-effort plain text from a resume. PDF via pypdf; otherwise decode."""
    name = (filename or "").lower()
    is_pdf = data[:4] == b"%PDF" or name.endswith(".pdf")
    if is_pdf:
        from pypdf import PdfReader  # local import: keeps stdlib-only importers happy
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                pass
        return "\n".join(parts)
    # .txt / .md / anything decodable
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _clean_phone(raw: str) -> Optional[str]:
    n = len(re.sub(r"\D", "", raw))
    if not (7 <= n <= 15):
        return None
    # Require a phone-ish signal so we don't grab space-separated years/IDs
    # like "2015 2018 2021": a +, bracket, dash, or a 10+ digit contiguous run.
    longest_run = max((len(g) for g in re.findall(r"\d+", raw)), default=0)
    if re.search(r"[+()\-]", raw) or longest_run >= 10:
        return raw.strip()
    return None


def _guess_name(text: str, email: Optional[str]) -> Optional[str]:
    """Heuristic: the first short, title-cased, label-free line near the top is
    usually the person's name. Fall back to the email local part."""
    for line in text.splitlines()[:12]:
        s = line.strip()
        if not s or _LABELISH.search(s):
            continue
        if _EMAIL.search(s) or _URL.search(s) or any(ch.isdigit() for ch in s):
            continue
        words = s.split()
        if not (1 < len(words) <= 4):
            continue
        # mostly alphabetic, looks like a name (each word starts upper / all caps)
        if all(re.fullmatch(r"[A-Za-z][A-Za-z.'\-]*", w) for w in words) and \
           sum(1 for w in words if w[:1].isupper() or w.isupper()) >= 2:
            return " ".join(w.capitalize() if w.isupper() else w for w in words)
    if email:
        local = email.split("@", 1)[0]
        parts = re.split(r"[._\-]+", local)
        parts = [p for p in parts if p.isalpha()]
        if len(parts) >= 2:
            return " ".join(p.capitalize() for p in parts[:3])
    return None


def extract_facts(text: str) -> List[Dict[str, str]]:
    """Return learn-style pairs [{key, value, label}] for the fields we can read
    deterministically. Keys match rag.learn.LEARNABLE / rag.resolver keys."""
    pairs: List[Dict[str, str]] = []
    seen = set()

    def add(key: str, value: Optional[str], label: str):
        if value and key not in seen:
            pairs.append({"key": key, "value": value.strip(), "label": label})
            seen.add(key)

    email_m = _EMAIL.search(text)
    email = email_m.group(0) if email_m else None
    add("email", email, "Email")

    li = _LINKEDIN.search(text)
    if li:
        url = li.group(0)
        add("linkedin", url if url.lower().startswith("http") else "https://" + url, "LinkedIn")

    gh = _GITHUB.search(text)
    if gh:
        url = gh.group(0)
        add("github", url if url.lower().startswith("http") else "https://" + url, "GitHub")

    for m in _PHONE.finditer(text):
        ph = _clean_phone(m.group(1))
        if ph:
            add("phone", ph, "Phone")
            break

    add("name", _guess_name(text, email), "Full name")
    return pairs
