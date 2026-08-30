"""Form analysis API (token-guarded).

Phase 2 endpoint: accept a perceived form and return a structured summary so we
can confirm perception works and see, at a glance, what's labeled, what's
fillable, and what will be left for manual entry (secrets). No profile matching
happens here — that arrives in Phase 4.
"""
from fastapi import APIRouter, Depends

from ..security import require_token
from .schema import PerceivedForm

router = APIRouter(prefix="/forms", tags=["forms"])


@router.post("/analyze", dependencies=[Depends(require_token)])
def analyze(form: PerceivedForm) -> dict:
    by_type: dict = {}
    for f in form.fields:
        by_type[f.type] = by_type.get(f.type, 0) + 1

    unlabeled = [f for f in form.fields if not f.label]
    sensitive = [f for f in form.fields if f.sensitive]
    fillable = [f for f in form.fields if not f.sensitive]

    return {
        "ok": True,
        "url": form.url,
        "title": form.title,
        "total": len(form.fields),
        "by_type": by_type,
        "labeled": len(form.fields) - len(unlabeled),
        "unlabeled": len(unlabeled),
        "sensitive": len(sensitive),
        "fillable": len(fillable),
        "unlabeled_selectors": [f.selector for f in unlabeled][:25],
        "sensitive_fields": [
            {"selector": f.selector, "label": f.label, "reason": f.sensitive_reason}
            for f in sensitive
        ],
    }
