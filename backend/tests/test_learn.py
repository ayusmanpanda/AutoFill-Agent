"""Offline tests for the 'learn from page' backend logic. Pure stdlib — no web
stack, no network, no pip deps. Run from the backend/ folder:

    python3 tests/test_learn.py

Covers the three composable pieces of POST /profile/learn:
  * resolver.key_for_field  — maps a field to a key even when the slot is empty
  * classifier.classify_field — authoritatively refuses SECRET fields
  * learn.apply_learned      — fills empty slots only, validates, is non-destructive
And the end-to-end invariant: a value learned into the profile is read straight
back by flatten (learn -> next fill round-trip).
"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.privacy.classifier import Sensitivity, classify_field
from app.rag.flatten import facts_by_key, flatten_profile
from app.rag.learn import LEARNABLE, NON_LEARNABLE_REASON, apply_learned
from app.rag.resolver import key_for_field

passed = 0


def test(name, fn):
    global passed
    fn()
    passed += 1
    print("  ok -", name)


def F(**kw):
    base = dict(autocomplete=None, label=None, name=None, placeholder=None,
                group=None, type="text", sensitive=False, value=None)
    base.update(kw)
    return NS(**base)


def to_ns(obj):
    """Recursively turn the learned profile dict into attribute objects so the
    duck-typed flatten (getattr-based) can read it — same as a Pydantic model."""
    if isinstance(obj, dict):
        return NS(**{k: to_ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [to_ns(v) for v in obj]
    return obj


# ---------------- key_for_field: resolves even with an empty profile ----------
def _keys():
    assert key_for_field(F(label="LinkedIn URL")) == "linkedin"
    assert key_for_field(F(label="GitHub")) == "github"
    assert key_for_field(F(label="Portfolio site")) == "portfolio"
    assert key_for_field(F(autocomplete="email")) == "email"
    assert key_for_field(F(label="Phone number")) == "phone"
    assert key_for_field(F(label="City")) == "city"
    assert key_for_field(F(label="Totally unknown blah")) is None
test("key_for_field maps links/contact even when the slot is empty", _keys)


# ---------------- classifier: secrets are refused --------------------------
def _secrets():
    assert classify_field(F(type="password", label="Password"))[0] == Sensitivity.SECRET
    assert classify_field(F(label="CVV", name="cvv"))[0] == Sensitivity.SECRET
    assert classify_field(F(label="OTP", name="user_otp"))[0] == Sensitivity.SECRET
    assert classify_field(F(label="SSN"))[0] == Sensitivity.SECRET
    # a linkedin url is not secret
    assert classify_field(F(label="LinkedIn URL"))[0] != Sensitivity.SECRET
test("classifier flags password/CVV/OTP/SSN as SECRET, links as not-secret", _secrets)


# ---------------- apply_learned: the user's LinkedIn scenario --------------
def _linkedin():
    prof = {"basics": {"name": "Ada"}, "job_preferences": {}}
    res = apply_learned(prof, [
        {"key": "linkedin", "value": "https://linkedin.com/in/ada", "label": "LinkedIn URL"},
    ])
    assert res["profile"]["job_preferences"]["linkedin"] == "https://linkedin.com/in/ada"
    assert len(res["applied"]) == 1 and res["applied"][0]["key"] == "linkedin"
    # input not mutated
    assert "linkedin" not in prof["job_preferences"]
test("apply_learned fills empty linkedin slot (job_preferences)", _linkedin)


def _nondestructive():
    prof = {"job_preferences": {"linkedin": "https://linkedin.com/in/OLD"}}
    res = apply_learned(prof, [
        {"key": "linkedin", "value": "https://linkedin.com/in/NEW", "label": "LinkedIn"},
    ])
    # existing value kept — never overwritten
    assert res["profile"]["job_preferences"]["linkedin"] == "https://linkedin.com/in/OLD"
    assert not res["applied"]
    assert any("already set" in s["reason"] for s in res["skipped"])
test("apply_learned is non-destructive (keeps existing profile values)", _nondestructive)


def _validation():
    prof = {"basics": {}, "job_preferences": {}}
    res = apply_learned(prof, [
        {"key": "email", "value": "not-an-email", "label": "Email"},
        {"key": "linkedin", "value": "has spaces so invalid", "label": "LinkedIn"},
        {"key": "phone", "value": "abc", "label": "Phone"},
        {"key": "email", "value": "ada@example.com", "label": "Email"},  # dup key after invalid
    ])
    # nothing valid was applied for email (first invalid, then the valid one is a dup? no:
    # the invalid one is skipped, so the valid email IS applied)
    applied_keys = {a["key"] for a in res["applied"]}
    assert "email" in applied_keys, res
    assert res["profile"]["basics"]["email"] == "ada@example.com"
    assert "linkedin" not in res["profile"].get("job_preferences", {})
    assert "phone" not in res["profile"].get("basics", {})
test("apply_learned rejects malformed email/url/phone by kind", _validation)


def _refusals():
    prof = {"basics": {}, "job_preferences": {}, "voluntary": {}}
    res = apply_learned(prof, [
        {"key": "gender", "value": "X", "label": "Gender"},          # EEO — never learned
        {"key": "skills", "value": "Python", "label": "Skills"},     # list — not learnable
        {"key": "given_name", "value": "Ada", "label": "First name"},# derived — not learnable
        {"key": "password", "value": "hunter2", "label": "Password"},# not even a real key
    ])
    assert not res["applied"], "none of these should be learnable"
    reasons = {s["key"]: s["reason"] for s in res["skipped"]}
    assert "voluntary" in reasons["gender"] or "EEO" in reasons["gender"]
    # secret-ish keys are simply not in the whitelist
    assert "password" not in LEARNABLE
    for k in ("gender", "race_ethnicity", "veteran_status", "disability_status"):
        assert k in NON_LEARNABLE_REASON and k not in LEARNABLE
test("apply_learned refuses EEO/derived/list/secret keys", _refusals)


# ---------------- end-to-end: learn -> flatten reads it back ---------------
def _roundtrip():
    prof = {"basics": {"name": "Ada Lovelace", "location": {}}, "job_preferences": {}}
    learned = apply_learned(prof, [
        {"key": "linkedin", "value": "https://linkedin.com/in/ada", "label": "LinkedIn"},
        {"key": "github", "value": "https://github.com/ada", "label": "GitHub"},
        {"key": "city", "value": "London", "label": "City"},
    ])["profile"]
    facts = facts_by_key(flatten_profile(to_ns(learned)))
    # exactly what a subsequent fill would read for these keys
    assert facts["linkedin"]["value"] == "https://linkedin.com/in/ada"
    assert facts["github"]["value"] == "https://github.com/ada"
    assert facts["city"]["value"] == "London"
test("ROUND-TRIP: learned values are read straight back by flatten", _roundtrip)


# ---------------- every LEARNABLE path is a location flatten can read ------
def _paths_sane():
    # each learnable path is 2-3 segments and rooted at a real profile section
    roots = {"basics", "job_preferences"}
    for key, (path, kind) in LEARNABLE.items():
        assert path[0] in roots, (key, path)
        assert 2 <= len(path) <= 3
test("every LEARNABLE key writes under basics/job_preferences", _paths_sane)


if __name__ == "__main__":
    print(f"\n{passed} learn backend tests passed")
