"""Offline tests for Phase 7 PDF form handling. pypdf + stdlib only (NO pydantic /
FastAPI), so it runs in the sandbox. From the backend/ folder:

    python3 tests/test_pdf.py

Builds an in-memory AcroForm fixture, perceives it, plans against a profile
(reusing the RAG builder — importable without the web stack), fills it, and
re-reads to prove: identity fields are written, and the SSN (secret) stays EMPTY.
"""
import io
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, BooleanObject, DictionaryObject,
                           NameObject, NumberObject, TextStringObject)

from app.pdf.fill import fill_pdf, is_fillable
from app.pdf.perceive import perceive_pdf
from app.rag.plan import build_plan

passed = 0


def test(name, fn):
    global passed
    fn()
    passed += 1
    print("  ok -", name)


def make_pdf(text_fields):
    """text_fields: list of (name, tooltip). Returns AcroForm PDF bytes."""
    w = PdfWriter()
    w.add_blank_page(width=320, height=480)
    page = w.pages[0]
    refs = []
    y = 440
    for name, tu in text_fields:
        f = DictionaryObject()
        f.update({
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject(name),
            NameObject("/TU"): TextStringObject(tu),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Rect"): ArrayObject([NumberObject(v) for v in (20, y, 300, y + 18)]),
            NameObject("/V"): TextStringObject(""),
        })
        refs.append(w._add_object(f))
        y -= 30
    page[NameObject("/Annots")] = ArrayObject(refs)
    acro = DictionaryObject()
    acro.update({NameObject("/Fields"): ArrayObject(refs),
                 NameObject("/NeedAppearances"): BooleanObject(True)})
    w._root_object[NameObject("/AcroForm")] = w._add_object(acro)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


FIXTURE = make_pdf([
    ("email", "Email address"),
    ("full_name", "Full legal name"),
    ("linkedin", "LinkedIn profile URL"),
    ("city", "City"),
    ("ssn", "Social Security Number"),
])


def profile():
    return NS(
        basics=NS(name="Ada Lovelace", email="ada@example.com", phone=None,
                  website=None, headline=None, summary=None,
                  location=NS(address=None, city="London", region=None,
                              postal_code=None, country=None),
                  profiles=[]),
        work=[], education=[], skills=[], projects=[],
        job_preferences=NS(linkedin="https://linkedin.com/in/ada", github=None,
                           portfolio=None, work_authorization=None,
                           requires_sponsorship=None, desired_salary=None,
                           salary_currency=None, notice_period=None,
                           earliest_start_date=None, willing_to_relocate=None,
                           work_mode=None),
        voluntary=NS(gender=None, race_ethnicity=None, veteran_status=None,
                     disability_status=None),
    )


def as_form(perceived):
    """Turn perceive_pdf's dicts into duck-typed objects build_plan can read."""
    fields = []
    for d in perceived["fields"]:
        opts = [NS(**o) for o in d.get("options", [])]
        fields.append(NS(**{**d, "options": opts}))
    return NS(url=perceived["url"], fields=fields)


# ---------------- perception ----------------
def _perceive():
    p = perceive_pdf(FIXTURE, "app.pdf")
    by = {f["name"]: f for f in p["fields"]}
    assert set(by) == {"email", "full_name", "linkedin", "city", "ssn"}, by
    assert by["email"]["type"] == "text"
    assert by["email"]["label"] == "Email address"        # from /TU tooltip
    assert by["linkedin"]["label"] == "LinkedIn profile URL"
    # SSN flagged secret straight from perception's classify()
    assert by["ssn"]["sensitive"] is True
    assert by["email"]["sensitive"] is False
test("perceive_pdf reads fields, tooltips as labels, flags SSN secret", _perceive)


# ---------------- planning (reused RAG builder) ----------------
def _plan():
    form = as_form(perceive_pdf(FIXTURE, "app.pdf"))
    plan = build_plan(form, profile(), matcher=None)
    acts = {r["selector"]: (r["action"], r["value"]) for r in plan["fields"]}
    assert acts["email"] == ("fill", "ada@example.com"), acts
    assert acts["full_name"][0] == "fill" and "Ada" in acts["full_name"][1]
    assert acts["linkedin"] == ("fill", "https://linkedin.com/in/ada"), acts
    assert acts["city"] == ("fill", "London"), acts
    # the secret is never resolved or valued
    assert acts["ssn"][0] == "manual_entry" and acts["ssn"][1] is None, acts
test("build_plan fills identity fields, marks SSN manual_entry", _plan)


# ---------------- fill round-trip ----------------
def _fill():
    form = as_form(perceive_pdf(FIXTURE, "app.pdf"))
    plan = build_plan(form, profile(), matcher=None)
    filled_bytes, report = fill_pdf(FIXTURE, plan)
    got = PdfReader(io.BytesIO(filled_bytes)).get_fields()
    assert got["email"]["/V"] == "ada@example.com", got["email"]["/V"]
    assert "Ada" in str(got["full_name"]["/V"])
    assert got["linkedin"]["/V"] == "https://linkedin.com/in/ada"
    assert got["city"]["/V"] == "London"
    # THE privacy invariant: the secret field was never written
    assert str(got["ssn"].get("/V") or "") == "", got["ssn"].get("/V")
    assert "ssn" not in report["filled"]
    assert report["counts"]["filled"] == 4, report
test("fill_pdf writes identity fields and leaves SSN EMPTY", _fill)


# ---------------- is_fillable gate ----------------
def _gate():
    assert is_fillable({"action": "fill", "sensitivity": "safe", "value": "x", "selector": "a"})
    assert not is_fillable({"action": "fill", "sensitivity": "secret", "value": "x"})
    assert not is_fillable({"action": "manual_entry", "sensitivity": "secret", "value": None})
    assert not is_fillable({"action": "fill", "sensitivity": "pii", "value": ""})
    assert not is_fillable({"action": "unmapped", "sensitivity": "safe", "value": None})
    assert not is_fillable({"action": "generate", "sensitivity": "safe", "value": None})
test("is_fillable accepts only non-secret fill records with a value", _gate)


# ---------------- non-form PDF degrades gracefully ----------------
def _noform():
    w = PdfWriter(); w.add_blank_page(width=200, height=200)
    b = io.BytesIO(); w.write(b)
    p = perceive_pdf(b.getvalue(), "blank.pdf")
    assert p["fields"] == []
    out, rep = fill_pdf(b.getvalue(), {"fields": []})
    assert rep["counts"]["filled"] == 0 and out[:4] == b"%PDF"
test("a PDF with no form fields yields an empty plan, no crash", _noform)


if __name__ == "__main__":
    print(f"\n{passed} PDF tests passed")
