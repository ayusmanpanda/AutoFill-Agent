"""Authoritative sensitivity classifier (runs on the backend — never trusts the
client's flags). Every field is bucketed into one of three levels:

  SECRET  passwords, OTP/2FA, CAPTCHA, CVV, PIN, card/bank numbers, SSN.
          Never stored, never embedded, never sent to the LLM. Manual entry only.
  PII     email, phone, address, name, date of birth. Filled locally from the
          profile, but scrubbed out of anything sent to the cloud LLM.
  SAFE    everything else (job titles, skills, free-text questions). LLM-eligible.

Pure/stdlib only, so it can be unit-tested without the web stack.
"""
import re
from enum import Enum
from typing import Optional, Tuple


class Sensitivity(str, Enum):
    SECRET = "secret"
    PII = "pii"
    SAFE = "safe"


# Ordered secret rules — matched against name/label/placeholder/group/autocomplete.
_SECRET_RULES = [
    (re.compile(r"pass(word|wd|phrase)|\bpwd\b", re.I), "password"),
    (re.compile(r"\botp\b|one[\s-]?time|2fa|mfa|auth(entication)?[\s-]?code|verification[\s-]?code|security[\s-]?code", re.I), "OTP / verification code"),
    (re.compile(r"\bcaptcha\b|i'?m not a robot", re.I), "CAPTCHA"),
    (re.compile(r"\bcvv2?\b|\bcvc\b|\bcsc\b|card[\s-]?verification", re.I), "card security code"),
    (re.compile(r"card[\s-]?number|cardnumber|credit[\s-]?card|\bcc[\s-]?num", re.I), "card number"),
    (re.compile(r"\bpin\b(?![\s-]?code)", re.I), "PIN"),
    (re.compile(r"\bssn\b|social[\s-]?security", re.I), "SSN"),
    (re.compile(r"routing[\s-]?number|account[\s-]?number|\biban\b|\bswift\b|sort[\s-]?code", re.I), "bank account"),
]

# Ordered PII rules (only reached if not already SECRET).
_PII_RULES = [
    (re.compile(r"e-?mail", re.I), "email"),
    (re.compile(r"\bphone\b|mobile|telephone|\btel\b", re.I), "phone"),
    (re.compile(r"first[\s-]?name|last[\s-]?name|full[\s-]?name|given[\s-]?name|middle[\s-]?name|sur[\s-]?name|\bname\b", re.I), "name"),
    (re.compile(r"address|street|\bcity\b|\bstate\b|province|\bzip\b|postal|pin[\s-]?code|country", re.I), "address"),
    (re.compile(r"birth|\bdob\b|date of birth|\bage\b", re.I), "date of birth"),
]

_SECRET_AC_PREFIX = ("cc-",)
_SECRET_AC_EXACT = ("one-time-code",)

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _haystack(*parts: Optional[str]) -> str:
    """Normalize field metadata into space-separated tokens so that word-anchored
    rules (\\botp\\b, \\bpin\\b, \\bssn\\b, …) fire on snake_case and camelCase
    names. Without this, `user_otp` slips past `\\botp\\b` because `_` is a regex
    word character, and `userOtp` slips past it because there is no boundary
    between letters. Hyphens/apostrophes are left intact (rules use [\\s-]?)."""
    raw = " ".join(p for p in parts if p)
    raw = _CAMEL.sub(" ", raw)      # fooBar -> foo Bar
    return raw.replace("_", " ")    # user_otp -> user otp
_PII_AC = (
    "email", "tel", "tel-national", "name", "given-name", "additional-name",
    "family-name", "honorific-prefix", "street-address", "address-line1",
    "address-line2", "address-line3", "postal-code", "country", "country-name",
    "bday", "bday-day", "bday-month", "bday-year",
)


def classify(field_type=None, name=None, label=None, autocomplete=None,
             placeholder=None, group=None) -> Tuple[Sensitivity, Optional[str]]:
    ft = (field_type or "").lower()
    ac = (autocomplete or "").lower()

    # --- SECRET (checked first; strongest protection) ---
    if ft == "password":
        return Sensitivity.SECRET, "password"
    if ac in _SECRET_AC_EXACT or ac.startswith(_SECRET_AC_PREFIX):
        return Sensitivity.SECRET, "payment/OTP autocomplete"
    haystack = _haystack(name, label, placeholder, group, autocomplete)
    for rx, reason in _SECRET_RULES:
        if rx.search(haystack):
            return Sensitivity.SECRET, reason

    # --- PII ---
    if ft == "email":
        return Sensitivity.PII, "email"
    if ft == "tel":
        return Sensitivity.PII, "phone"
    if ac in _PII_AC:
        return Sensitivity.PII, "contact/identity autocomplete"
    for rx, reason in _PII_RULES:
        if rx.search(haystack):
            return Sensitivity.PII, reason

    return Sensitivity.SAFE, None


def classify_field(field) -> Tuple[Sensitivity, Optional[str]]:
    """Adapter for a PerceivedField (duck-typed — reads attributes only)."""
    return classify(
        field_type=getattr(field, "type", None),
        name=getattr(field, "name", None),
        label=getattr(field, "label", None),
        autocomplete=getattr(field, "autocomplete", None),
        placeholder=getattr(field, "placeholder", None),
        group=getattr(field, "group", None),
    )


_ACTION = {
    Sensitivity.SECRET: "manual_entry",       # user types it; we never touch it
    Sensitivity.PII: "fill_local_only",       # filled locally, scrubbed from LLM
    Sensitivity.SAFE: "eligible_for_llm",     # may be reasoned about by the model
}


def action_for(sensitivity: Sensitivity) -> str:
    return _ACTION[sensitivity]
