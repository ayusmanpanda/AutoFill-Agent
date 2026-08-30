"""Read an AcroForm PDF's fillable fields into a normalized structure.

This is the PDF counterpart to the browser extension's page perception. It uses
pypdf (pure-Python, no system libraries — easy to install and to share) to walk
the form fields and produce the SAME field shape the web path uses, so the rest
of the pipeline (sensitivity classifier + RAG fill-plan builder) is reused
unchanged.

Deliberately depends only on pypdf + the stdlib classifier — NOT on pydantic or
FastAPI — so it can be unit-tested offline. The router wraps the plain dicts this
returns into PerceivedForm/PerceivedField models for its response.

It NEVER reads a field's existing value for anything sent to the cloud; option
labels and field names are page content, treated like any web label.
"""
from typing import Any, Dict, List, Optional

from pypdf import PdfReader

from ..privacy.classifier import classify

# PDF field-type codes (/FT) -> our normalized types.
#   /Tx  text     /Ch choice (dropdown/list)   /Btn button (checkbox/radio/push)
_MULTILINE_FLAG = 1 << 12  # /Ff bit 13: text field is multiline -> treat as textarea


def _humanize(name: str) -> str:
    import re
    s = re.sub(r"[_\-.]+", " ", name or "")
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:1].upper() + s[1:] if s else s


def _str(v: Any) -> str:
    return "" if v is None else str(v)


def _states_for_button(field: Any) -> List[str]:
    """The 'on' state names of a checkbox/radio (everything except /Off)."""
    states = field.get("/_States_") if hasattr(field, "get") else None
    out = []
    if states:
        for s in states:
            name = _str(s).lstrip("/")
            if name and name.lower() != "off":
                out.append(name)
    # de-dup, preserve order
    seen = set()
    return [s for s in out if not (s in seen or seen.add(s))]


def _choice_options(field: Any) -> List[Dict[str, str]]:
    """Dropdown/list options from /Opt. Entries may be a string or [export, display]."""
    opts = field.get("/Opt") if hasattr(field, "get") else None
    out: List[Dict[str, str]] = []
    for o in opts or []:
        if isinstance(o, (list, tuple)) and len(o) >= 2:
            out.append({"value": _str(o[0]), "label": _str(o[1])})
        else:
            out.append({"value": _str(o), "label": _str(o)})
    return out


def _map_field(fid: str, name: str, field: Any) -> Optional[Dict[str, Any]]:
    ft = _str(field.get("/FT")) if hasattr(field, "get") else ""
    tu = _str(field.get("/TU")) if hasattr(field, "get") else ""       # tooltip = human label
    label = tu.strip() or _humanize(name)
    flags = 0
    try:
        flags = int(field.get("/Ff") or 0)
    except (TypeError, ValueError):
        flags = 0

    options: List[Dict[str, str]] = []
    if ft == "/Tx":
        ntype = "textarea" if (flags & _MULTILINE_FLAG) else "text"
    elif ft == "/Ch":
        ntype = "select"
        options = _choice_options(field)
    elif ft == "/Btn":
        states = _states_for_button(field)
        if len(states) > 1:
            ntype = "radio"
            options = [{"value": s, "label": _humanize(s)} for s in states]
        elif len(states) == 1:
            ntype = "checkbox"
            options = [{"value": states[0], "label": _humanize(states[0])}]
        else:
            # a pushbutton (no states) — nothing to fill
            return None
    else:
        return None  # signature or unknown field type: skip

    sens, reason = classify(field_type=ntype, name=name, label=label)
    return {
        "field_id": fid,
        "selector": name,          # the PDF field name; used to fill later
        "type": ntype,
        "label": label,
        "label_source": "tooltip" if tu.strip() else "name-fallback",
        "name": name,
        "options": options,
        "required": bool(flags & (1 << 1)),  # /Ff bit 2 = Required
        "sensitive": sens.value == "secret",
        "sensitive_reason": reason if sens.value == "secret" else None,
    }


def perceive_pdf(data: bytes, filename: Optional[str] = None) -> Dict[str, Any]:
    """Return {url, title, fields:[...]} for an AcroForm PDF. `url`/`title` carry
    the filename so the plan/summary reads naturally. Non-form PDFs yield []."""
    reader = PdfReader(__import__("io").BytesIO(data))
    fields = reader.get_fields() or {}

    out_fields: List[Dict[str, Any]] = []
    i = 0
    for name, field in fields.items():
        i += 1
        rec = _map_field("p%d" % i, _str(name), field)
        if rec is not None:
            out_fields.append(rec)
    return {"url": filename, "title": filename, "fields": out_fields}
