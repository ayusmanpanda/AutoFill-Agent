"""Privacy API (token-guarded): show what would/wouldn't be sent to the cloud.

  POST /privacy/plan        classify each field of a perceived form and report
                            per-field action + cloud-eligible vs kept-local counts.
  POST /privacy/scrub-test  preview the egress scrub on a piece of text.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..forms.schema import PerceivedForm
from ..profile import store
from ..security import require_token
from .classifier import action_for, classify_field
from .scrub import build_scrubber_from_profile

router = APIRouter(prefix="/privacy", tags=["privacy"])


@router.post("/plan", dependencies=[Depends(require_token)])
def plan(form: PerceivedForm) -> dict:
    counts = {"secret": 0, "pii": 0, "safe": 0}
    fields = []
    for f in form.fields:
        sens, reason = classify_field(f)
        counts[sens.value] += 1
        fields.append({
            "field_id": f.field_id,
            "label": f.label,
            "type": f.type,
            "sensitivity": sens.value,
            "reason": reason,
            "action": action_for(sens),
        })
    total = len(form.fields)
    return {
        "ok": True,
        "url": form.url,
        "total": total,
        "counts": {**counts, "total": total},
        "cloud_eligible": counts["safe"],
        "kept_local": counts["secret"] + counts["pii"],
        "fields": fields,
    }


class ScrubIn(BaseModel):
    text: str


@router.post("/scrub-test", dependencies=[Depends(require_token)])
def scrub_test(body: ScrubIn) -> dict:
    scrubber = build_scrubber_from_profile(store.get_profile())
    scrubbed = scrubber.scrub(body.text)
    # We return only the redacted text and per-type counts — never the map of
    # original values.
    return {
        "ok": True,
        "scrubbed": scrubbed,
        "redactions": scrubber.count,
        "redaction_types": scrubber.type_counts,
    }
