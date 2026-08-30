"""Write a fill plan into an AcroForm PDF — the PDF counterpart to lib/fill.js.

Only records the plan marked as a concrete `fill` are written, and only for
non-secret fields with a non-empty value. Secret / manual_entry / unmapped /
generate records are never touched, so the same privacy guarantee as the web
path holds on PDFs: passwords, SSNs, card/CVV/PIN etc. are left blank for the
user to enter by hand. The PDF is never submitted anywhere — we hand back the
filled bytes for the user to review and save.

pypdf-only (no pydantic/FastAPI) so it's unit-testable offline.
"""
import io
from typing import Any, Dict, List, Tuple

from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, NameObject


def is_fillable(rec: Dict[str, Any]) -> bool:
    """Defense-in-depth gate, mirroring lib/fill.js: only ever write a plain
    `fill` record for a non-secret field that actually has a value."""
    if not rec or rec.get("action") != "fill":
        return False
    if rec.get("sensitivity") == "secret":
        return False
    v = rec.get("value")
    return v is not None and str(v) != ""


def _set_need_appearances(writer: PdfWriter) -> None:
    """Ask viewers to regenerate field appearances so filled text is visible."""
    try:
        root = writer._root_object
        if "/AcroForm" in root:
            root["/AcroForm"][NameObject("/NeedAppearances")] = BooleanObject(True)
    except Exception:
        pass  # non-fatal: values are still written into the field dictionaries


def fill_pdf(data: bytes, plan: Dict[str, Any]) -> Tuple[bytes, Dict[str, Any]]:
    """Apply a plan's fillable records to the PDF. Returns (filled_bytes, report).

    report = {filled:[names], skipped:[names], not_found:[names], counts:{...}}.
    """
    fields = list((plan or {}).get("fields") or [])

    # Build name -> value from the fillable records only.
    to_fill: Dict[str, str] = {}
    filled: List[str] = []
    skipped: List[str] = []
    for rec in fields:
        name = rec.get("selector") or rec.get("name")
        if not name:
            continue
        if is_fillable(rec):
            to_fill[name] = str(rec.get("value"))
        else:
            skipped.append(name)

    reader = PdfReader(io.BytesIO(data))
    present = set((reader.get_fields() or {}).keys())

    writer = PdfWriter()
    writer.append(reader)

    not_found = [n for n in to_fill if n not in present]
    writable = {n: v for n, v in to_fill.items() if n in present}

    if writable:
        for page in writer.pages:
            try:
                writer.update_page_form_field_values(page, writable)
            except Exception:
                # A page without these fields raises; that's fine — try the rest.
                pass
    _set_need_appearances(writer)

    filled = [n for n in writable]
    out = io.BytesIO()
    writer.write(out)

    report = {
        "filled": filled,
        "skipped": skipped,
        "not_found": not_found,
        "counts": {
            "filled": len(filled),
            "skipped": len(skipped),
            "not_found": len(not_found),
        },
    }
    return out.getvalue(), report
