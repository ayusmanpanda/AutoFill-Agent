"""Fill-plan API (token-guarded).

  POST /fill/plan            build a per-field fill plan for a perceived form.
                             Query ?use_llm=false forces a pure-local run (no
                             cloud call at all — deterministic matches only).

The plan only describes what *would* be filled; it does not touch the page. The
extension applies it with human review in a later phase. Resolved values are
returned over loopback to the local extension only — never to the cloud.
"""
from fastapi import APIRouter, Depends

from ..forms.schema import PerceivedForm
from ..profile import store
from ..security import require_token
from .mapper import llm_match
from .plan import build_plan

router = APIRouter(prefix="/fill", tags=["fill"])


@router.post("/plan", dependencies=[Depends(require_token)])
def plan(form: PerceivedForm, use_llm: bool = True) -> dict:
    profile = store.get_profile()
    matcher = llm_match if use_llm else None
    return build_plan(form, profile, matcher=matcher)
