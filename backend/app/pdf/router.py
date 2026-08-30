"""PDF form filling API (token-guarded, multipart uploads).

  POST /pdf/analyze   upload a PDF -> normalized fields + summary (no fill)
  POST /pdf/plan      upload a PDF -> per-field fill plan (?use_llm, same as web)
  POST /pdf/fill      upload a PDF -> the FILLED PDF streamed back as a download

The pipeline reuses the exact classifier + RAG plan builder the web path uses, so
the privacy guarantees carry over: secret fields (SSN, card, CVV, PIN, bank …) are
classified SECRET and left blank for manual entry. The filled PDF is returned to
the caller over loopback and never submitted anywhere.
"""
import io
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ..forms.schema import PerceivedField, PerceivedForm
from ..profile import store
from ..rag.mapper import llm_match
from ..rag.plan import build_plan
from ..security import require_token
from .fill import fill_pdf
from .perceive import perceive_pdf

router = APIRouter(prefix="/pdf", tags=["pdf"])

_MAX_BYTES = 25 * 1024 * 1024  # refuse absurdly large uploads


async def _read_pdf(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="PDF too large (25MB max).")
    if data[:4] != b"%PDF":
        raise HTTPException(status_code=400, detail="Not a PDF file.")
    return data


def _to_form(perceived: dict) -> PerceivedForm:
    fields: List[PerceivedField] = []
    for d in perceived["fields"]:
        fields.append(PerceivedField.model_validate(d))
    return PerceivedForm(url=perceived.get("url"), title=perceived.get("title"),
                         fields=fields)


def _summary(form: PerceivedForm) -> dict:
    sensitive = [f for f in form.fields if f.sensitive]
    return {
        "total": len(form.fields),
        "by_type": _count_by(f.type for f in form.fields),
        "sensitive": [
            {"label": f.label or f.name, "reason": f.sensitive_reason} for f in sensitive
        ],
        "fillable": sum(1 for f in form.fields if not f.sensitive),
    }


def _count_by(values) -> dict:
    out: dict = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


@router.post("/analyze", dependencies=[Depends(require_token)])
async def analyze(file: UploadFile = File(...)) -> dict:
    data = await _read_pdf(file)
    try:
        perceived = perceive_pdf(data, file.filename)
    except Exception as e:  # a malformed PDF shouldn't 500 the whole app
        raise HTTPException(status_code=422, detail="Could not read PDF: %s" % e)
    form = _to_form(perceived)
    return {"ok": True, "form": form.model_dump(), "summary": _summary(form)}


@router.post("/plan", dependencies=[Depends(require_token)])
async def plan(file: UploadFile = File(...), use_llm: bool = True) -> dict:
    data = await _read_pdf(file)
    try:
        form = _to_form(perceive_pdf(data, file.filename))
    except Exception as e:
        raise HTTPException(status_code=422, detail="Could not read PDF: %s" % e)
    matcher = llm_match if use_llm else None
    return build_plan(form, store.get_profile(), matcher=matcher)


@router.post("/fill", dependencies=[Depends(require_token)])
async def fill(file: UploadFile = File(...), use_llm: bool = True) -> StreamingResponse:
    data = await _read_pdf(file)
    try:
        form = _to_form(perceive_pdf(data, file.filename))
    except Exception as e:
        raise HTTPException(status_code=422, detail="Could not read PDF: %s" % e)
    matcher = llm_match if use_llm else None
    plan_obj = build_plan(form, store.get_profile(), matcher=matcher)
    filled, report = fill_pdf(data, plan_obj)

    name = (file.filename or "form.pdf").rsplit(".", 1)[0] + ".filled.pdf"
    headers = {
        "Content-Disposition": 'attachment; filename="%s"' % name,
        "X-Autofill-Filled": str(report["counts"]["filled"]),
        "X-Autofill-Skipped": str(report["counts"]["skipped"]),
        "X-Autofill-Not-Found": str(report["counts"]["not_found"]),
    }
    return StreamingResponse(io.BytesIO(filled), media_type="application/pdf",
                             headers=headers)
