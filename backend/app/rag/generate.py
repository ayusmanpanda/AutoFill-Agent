"""Phase 5 — answer generation for free-text ("generate") fields.

Writes cover-letter-style answers to open questions ("Why do you want to work
here?", "Tell us about yourself") grounded in the user's profile. Guardrails:
first person, use ONLY facts present in the profile (no invented employers /
titles / dates / degrees), respect any character limit, no leftover placeholders.

All generation flows through the injected `completion` callable, which in
production is privacy.guard.safe_completion (scrub PII -> call model ->
rehydrate). To keep the pure helpers importable/testable in the offline sandbox,
safe_completion is imported lazily inside the functions that need it — the module
top stays stdlib-only.
"""
import json
import re
from typing import Any, Callable, Dict, List, Optional


def _g(obj: Any, *path: str) -> Optional[Any]:
    cur = obj
    for p in path:
        if cur is None:
            return None
        cur = getattr(cur, p, None)
    return cur


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _profile_parts(profile: Any) -> Dict[str, Any]:
    basics = _g(profile, "basics")
    parts: Dict[str, Any] = {
        "name": _s(_g(basics, "name")),
        "headline": _s(_g(basics, "headline")),
        "summary": _s(_g(basics, "summary")),
    }

    roles = []
    for w in (_g(profile, "work") or [])[:3]:
        pos, comp = _s(_g(w, "position")), _s(_g(w, "company"))
        if pos or comp:
            span = " - ".join(x for x in (_s(_g(w, "start_date")), _s(_g(w, "end_date"))) if x)
            roles.append((pos, comp, span))
    parts["roles"] = roles

    highlights: List[str] = []
    for w in (_g(profile, "work") or []):
        highlights += [_s(h) for h in (_g(w, "highlights") or []) if _s(h)]
    for p in (_g(profile, "projects") or []):
        highlights += [_s(h) for h in (_g(p, "highlights") or []) if _s(h)]
        if _s(_g(p, "description")):
            highlights.append(_s(_g(p, "description")))
    parts["highlights"] = highlights

    parts["skills"] = [_s(_g(s, "name")) for s in (_g(profile, "skills") or []) if _s(_g(s, "name"))]

    edu = []
    for e in (_g(profile, "education") or [])[:2]:
        deg = " ".join(x for x in (_s(_g(e, "study_type")), _s(_g(e, "area"))) if x)
        inst = _s(_g(e, "institution"))
        if deg or inst:
            edu.append((deg, inst))
    parts["education"] = edu
    return parts


def profile_digest(profile: Any, max_highlights: int = 12) -> str:
    """Compact, plain-text grounding context for generation."""
    L = _profile_parts(profile)
    out: List[str] = []
    who = " - ".join(x for x in (L["name"], L["headline"]) if x)
    if who:
        out.append("Candidate: " + who)
    if L["summary"]:
        out.append("Summary: " + L["summary"])
    if L["roles"]:
        rlines = []
        for pos, comp, span in L["roles"]:
            r = " at ".join(x for x in (pos, comp) if x)
            if span:
                r += " (" + span + ")"
            rlines.append(r)
        out.append("Experience: " + "; ".join(rlines))
    if L["skills"]:
        out.append("Skills: " + ", ".join(L["skills"]))
    if L["highlights"]:
        out.append("Highlights:\n" + "\n".join("- " + h for h in L["highlights"][:max_highlights]))
    if L["education"]:
        out.append("Education: " + "; ".join(
            " at ".join(x for x in (deg, inst) if x) for deg, inst in L["education"]))
    return "\n".join(out)


_STOP = set(
    "the a an and or of to for with in on at by from your you our we as is are be this that "
    "will do does can could would how why what who which when where describe tell about role "
    "position company job work experience please give example time".split()
)


def _tokens(s: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) >= 3 and w not in _STOP]


def retrieve_highlights(profile: Any, query: str, k: int = 6) -> List[str]:
    """Lightweight lexical RAG: rank profile highlights by token overlap with the
    question. Falls back to original order when nothing overlaps."""
    highlights = _profile_parts(profile)["highlights"]
    if not highlights:
        return []
    q = set(_tokens(query))
    scored = []
    for i, h in enumerate(highlights):
        scored.append((len(q & set(_tokens(h))), i, h))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [h for _, _, h in scored[:k]]


_SYSTEM_TMPL = (
    "You are helping a job candidate answer application questions in their own voice "
    "({tone}, first person). Use ONLY the facts in the candidate profile below. Do NOT "
    "invent employers, job titles, dates, degrees, or achievements that are not present. "
    "If the profile lacks specifics for a question, write a brief, honest, general answer "
    "without fabricating details. Keep each answer focused, no leftover placeholders, and "
    "respect any stated character limit. "
    'Respond with ONLY a JSON object shaped like {{"answers": {{"<field_id>": "<answer>"}}}} '
    "and nothing else."
)

_JSON_OBJ = re.compile(r"\{.*\}", re.S)


def build_answer_prompt(questions: List[Dict[str, Any]], context: str,
                        tone: str = "professional") -> (str, str):
    system = _SYSTEM_TMPL.format(tone=tone)
    qlines = []
    for q in questions:
        text = q.get("question") or ""
        ml = q.get("max_length")
        if ml:
            text += " (max %d characters)" % ml
        qlines.append({"field_id": q.get("field_id"), "question": text})
    user = (
        "Candidate profile:\n" + (context or "(no profile details provided)") +
        "\n\nAnswer each question below in the candidate's voice. Return JSON keyed by "
        "field_id.\nQuestions:\n" + json.dumps(qlines, ensure_ascii=False)
    )
    return system, user


def parse_answers(raw: str, valid_ids: set) -> Dict[str, str]:
    if not raw:
        return {}
    m = _JSON_OBJ.search(raw)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except Exception:
        return {}
    answers = data.get("answers", data) if isinstance(data, dict) else {}
    if not isinstance(answers, dict):
        return {}
    out: Dict[str, str] = {}
    for fid, val in answers.items():
        if fid in valid_ids and isinstance(val, str) and val.strip():
            out[fid] = val.strip()
    return out


def generate_answers(questions: List[Dict[str, Any]], profile: Any,
                     completion: Optional[Callable] = None,
                     tone: str = "professional",
                     max_tokens: Optional[int] = None) -> Dict[str, str]:
    """Batched: one model call answers all questions. Returns {field_id: answer}."""
    questions = [q for q in (questions or []) if q.get("question")]
    if not questions:
        return {}
    if completion is None:
        from ..privacy.guard import safe_completion as completion  # lazy: keeps module stdlib-only
    system, user = build_answer_prompt(questions, profile_digest(profile), tone)
    if max_tokens is None:
        max_tokens = min(1600, 200 + 220 * len(questions))
    out = completion(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens,
    )
    return parse_answers(out.get("reply", ""), {q.get("field_id") for q in questions})


def single_answer(question: str, profile: Any, completion: Optional[Callable] = None,
                  max_length: Optional[int] = None, tone: str = "professional") -> Dict[str, Any]:
    """One targeted answer, grounded via lexical retrieval over highlights."""
    if not question:
        return {"answer": "", "redactions": 0}
    if completion is None:
        from ..privacy.guard import safe_completion as completion
    L = _profile_parts(profile)
    ctx = []
    who = " - ".join(x for x in (L["name"], L["headline"]) if x)
    if who:
        ctx.append("Candidate: " + who)
    if L["summary"]:
        ctx.append("Summary: " + L["summary"])
    if L["skills"]:
        ctx.append("Skills: " + ", ".join(L["skills"]))
    hl = retrieve_highlights(profile, question, k=6)
    if hl:
        ctx.append("Relevant highlights:\n" + "\n".join("- " + h for h in hl))
    fid = "q1"
    system, user = build_answer_prompt(
        [{"field_id": fid, "question": question, "max_length": max_length}], "\n".join(ctx), tone)
    max_tokens = 400 if not max_length else min(600, max(120, max_length // 3))
    out = completion(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens,
    )
    return {"answer": parse_answers(out.get("reply", ""), {fid}).get(fid, ""),
            "redactions": out.get("redactions", 0)}


def _recount(fields: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = {"fill": 0, "manual_entry": 0, "generate": 0, "unmapped": 0}
    for r in fields:
        summary[r["action"]] = summary.get(r["action"], 0) + 1
    summary["total"] = len(fields)
    return summary


def apply_generated_answers(plan: Dict[str, Any], form: Any, profile: Any,
                            completion: Optional[Callable] = None,
                            tone: str = "professional",
                            max_fields: int = 8) -> Dict[str, Any]:
    """Fill the plan's 'generate' fields with written answers. A generate field
    that gets text becomes action 'fill' with via 'generated'; unanswered ones
    stay 'generate'. Returns the plan with a refreshed summary."""
    gen_ids = [r["field_id"] for r in plan.get("fields", []) if r.get("action") == "generate"]
    gen_ids = gen_ids[:max_fields]
    if not gen_ids:
        return plan

    by_id = {getattr(f, "field_id", None): f for f in (getattr(form, "fields", None) or [])}
    questions = []
    for fid in gen_ids:
        f = by_id.get(fid)
        if f is None:
            continue
        q = getattr(f, "label", None) or getattr(f, "group", None) or getattr(f, "name", None) or ""
        questions.append({"field_id": fid, "question": q, "max_length": getattr(f, "max_length", None)})

    answers = generate_answers(questions, profile, completion=completion, tone=tone)

    for r in plan.get("fields", []):
        if r.get("action") == "generate" and r["field_id"] in answers:
            r["value"] = answers[r["field_id"]]
            r["action"] = "fill"
            r["via"] = "generated"
            r["confidence"] = 0.6
            r["reason"] = "generated answer"

    plan["summary"] = _recount(plan.get("fields", []))
    plan["generated"] = sum(1 for r in plan.get("fields", []) if r.get("via") == "generated")
    return plan
