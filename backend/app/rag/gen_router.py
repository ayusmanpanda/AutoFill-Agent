"""Answer-generation API (token-guarded) — Phase 5.

  POST /generate/answers   build a fill plan for a perceived form, then write
                           the free-text ('generate') fields from the profile.
                           Returns the plan with those fields promoted to
                           action=fill, via=generated. Query ?use_llm=false uses
                           the deterministic mapper for the plan step; the answer
                           writing itself always needs the model.
  POST /generate/answer    write a single answer to one free-text question.

Generation is grounded ONLY in the stored profile and routed through
safe_completion (scrub PII -> model -> rehydrate). Secrets are never involved:
only SAFE free-text fields are ever 'generate' candidates, so nothing sensitive
reaches this path.
"""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..forms.schema import PerceivedForm
from ..profile import store
from ..security import require_token
from .generate import apply_generated_answers, single_answer
from .mapper import llm_match
from .plan import build_plan

router = APIRouter(prefix="/generate", tags=["generate"])


@router.post("/answers", dependencies=[Depends(require_token)])
def answers(form: PerceivedForm, use_llm: bool = True, tone: str = "professional") -> dict:
    profile = store.get_profile()
    matcher = llm_match if use_llm else None
    plan = build_plan(form, profile, matcher=matcher)
    return apply_generated_answers(plan, form, profile, tone=tone)


class SingleAnswerRequest(BaseModel):
    question: str
    max_length: Optional[int] = None
    tone: str = "professional"


@router.post("/answer", dependencies=[Depends(require_token)])
def answer(req: SingleAnswerRequest) -> dict:
    profile = store.get_profile()
    return single_answer(req.question, profile, max_length=req.max_length, tone=req.tone)
