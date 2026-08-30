"""Offline tests for resume import parsing. pypdf + stdlib only (NO pydantic /
FastAPI), so it runs in the sandbox:

    python3 tests/test_resume.py

Covers the deterministic text -> facts extraction and the learn-style merge into
a profile dict (fill empty slots only). PDF *binary* text extraction is exercised
lightly (graceful on a no-text PDF); the field-parsing logic is tested on text.
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.profile.resume import extract_facts, extract_text
from app.rag.learn import apply_learned

passed = 0


def test(name, fn):
    global passed
    fn()
    passed += 1
    print("  ok -", name)


RESUME = """Ada Lovelace
Senior Software Engineer

ada.lovelace@example.com  |  +1 (415) 555-0198  |  London, UK
linkedin.com/in/ada-lovelace   https://github.com/ada-lovelace

SUMMARY
First programmer. Builds analytical engines.
"""


def _facts():
    facts = {p["key"]: p["value"] for p in extract_facts(RESUME)}
    assert facts.get("email") == "ada.lovelace@example.com", facts
    assert facts.get("linkedin") == "https://linkedin.com/in/ada-lovelace", facts
    assert facts.get("github") == "https://github.com/ada-lovelace", facts
    assert "555-0198" in facts.get("phone", ""), facts
    assert facts.get("name") == "Ada Lovelace", facts
test("extract_facts pulls email, linkedin, github, phone, name", _facts)


def _no_secrets_or_junk():
    # Nothing secret-shaped is ever produced (only whitelisted keys exist).
    keys = {p["key"] for p in extract_facts(RESUME)}
    assert keys <= {"email", "phone", "linkedin", "github", "name", "website"}, keys
    # A page of years/ids shouldn't invent a phone from a 4-digit year.
    facts = {p["key"]: p["value"] for p in extract_facts("Experience 2015 2018 2021")}
    assert "phone" not in facts, facts
test("extract_facts yields only whitelisted keys, no false phone from years", _no_secrets_or_junk)


def _merge_fills_empty_only():
    profile = {"basics": {"name": "", "email": "existing@keep.me",
                          "location": {"city": None}},
               "job_preferences": {"linkedin": None, "github": None}}
    out = apply_learned(profile, extract_facts(RESUME))
    prof = out["profile"]
    # empty name filled; existing email kept (non-destructive)
    assert prof["basics"]["name"] == "Ada Lovelace", prof
    assert prof["basics"]["email"] == "existing@keep.me", prof
    assert prof["job_preferences"]["linkedin"] == "https://linkedin.com/in/ada-lovelace"
    reasons = {s["key"]: s["reason"] for s in out["skipped"]}
    assert reasons.get("email", "").startswith("already set"), reasons
test("apply_learned fills empty slots, never overwrites existing", _merge_fills_empty_only)


def _txt_extract():
    text = extract_text(b"jane@doe.io\nhttps://github.com/jane", "cv.txt")
    facts = {p["key"]: p["value"] for p in extract_facts(text)}
    assert facts.get("email") == "jane@doe.io", facts
    assert facts.get("github") == "https://github.com/jane", facts
test("extract_text decodes .txt and facts parse from it", _txt_extract)


def _pdf_no_text_graceful():
    from pypdf import PdfWriter
    w = PdfWriter(); w.add_blank_page(width=200, height=200)
    b = io.BytesIO(); w.write(b)
    text = extract_text(b.getvalue(), "blank.pdf")
    assert extract_facts(text) == [], text  # no crash, nothing invented
test("a text-less PDF extracts to no facts, no crash", _pdf_no_text_graceful)


if __name__ == "__main__":
    print(f"\n{passed} resume tests passed")
