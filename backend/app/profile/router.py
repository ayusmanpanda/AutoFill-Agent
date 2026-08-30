"""Profile CRUD API (all endpoints guarded by the local token)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict

from ..privacy.classifier import Sensitivity, classify_field
from ..rag.learn import apply_learned
from ..rag.resolver import key_for_field
from ..security import require_token
from . import store
from .resume import extract_facts, extract_text
from .schema import Profile

router = APIRouter(prefix="/profile", tags=["profile"])

# Separate router for managing multiple people's profiles (list/create/switch).
profiles_router = APIRouter(prefix="/profiles", tags=["profiles"])


class ProfileName(BaseModel):
    name: str


@profiles_router.get("", dependencies=[Depends(require_token)])
def list_profiles() -> dict:
    """All profiles (id, name, updated_at, active) so the popup can offer a
    'select who you are' picker on open."""
    return {"profiles": store.list_profiles()}


@profiles_router.post("", dependencies=[Depends(require_token)])
def create_profile(body: ProfileName) -> dict:
    """Create a new empty profile and make it active."""
    try:
        return store.create_profile(body.name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@profiles_router.post("/{profile_id}/activate", dependencies=[Depends(require_token)])
def activate_profile(profile_id: int) -> dict:
    """Switch the active profile — everything (fill/pdf/learn) then uses it."""
    try:
        return {"active": store.set_active(profile_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="No such profile.")


@profiles_router.patch("/{profile_id}", dependencies=[Depends(require_token)])
def rename_profile(profile_id: int, body: ProfileName) -> dict:
    try:
        return store.rename_profile(profile_id, body.name)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such profile.")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@profiles_router.delete("/{profile_id}", dependencies=[Depends(require_token)])
def delete_profile(profile_id: int) -> dict:
    try:
        return {"active": store.delete_profile(profile_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="No such profile.")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))



class LearnField(BaseModel):
    """One field read back from a page for the 'learn' feature. Carries its
    current value (SECRET fields are never sent here — and are refused again
    below regardless). extra='ignore' so any extra keys from the page are
    dropped harmlessly."""
    model_config = ConfigDict(extra="ignore")
    field_id: Optional[str] = None
    label: Optional[str] = None
    name: Optional[str] = None
    autocomplete: Optional[str] = None
    placeholder: Optional[str] = None
    group: Optional[str] = None
    type: Optional[str] = None
    sensitive: bool = False
    value: Optional[str] = None


class LearnForm(BaseModel):
    url: Optional[str] = None
    title: Optional[str] = None
    fields: List[LearnField] = []


@router.get("", dependencies=[Depends(require_token)])
def read_profile() -> Profile:
    """Return the stored profile (an empty template if none saved yet)."""
    return store.get_profile()


@router.put("", dependencies=[Depends(require_token)])
def write_profile(profile: Profile) -> Profile:
    """Validate and save the full profile."""
    return store.save_profile(profile)


@router.get("/completeness", dependencies=[Depends(require_token)])
def completeness() -> dict:
    """A quick summary of which key sections are filled in."""
    p = store.get_profile()
    checks = {
        "name": bool(p.basics.name),
        "email": bool(p.basics.email),
        "phone": bool(p.basics.phone),
        "location": bool(p.basics.location.city or p.basics.location.country),
        "work": len(p.work) > 0,
        "education": len(p.education) > 0,
        "skills": len(p.skills) > 0,
        "work_authorization": bool(p.job_preferences.work_authorization),
    }
    filled = sum(1 for v in checks.values() if v)
    return {
        "filled": filled,
        "total": len(checks),
        "percent": round(100 * filled / len(checks)),
        "checks": checks,
    }


@router.post("/learn", dependencies=[Depends(require_token)])
def learn(payload: LearnForm) -> dict:
    """Learn values a user typed on a page back into the profile.

    Purely local — NO LLM, no network egress. For each field we:
      1. Re-classify it authoritatively and REFUSE anything SECRET (or flagged
         sensitive) — a page secret is never read here, so it can't be stored.
      2. Resolve it to a profile key (value-independent, so empty slots resolve).
      3. Fill it via apply_learned, which writes ONLY empty slots (non-destructive)
         and only for the whitelisted single-value keys.
    """
    prof_dict = store.get_profile().model_dump()

    pairs = []
    refused_secret = 0
    for f in payload.fields:
        sens, _reason = classify_field(f)
        if sens == Sensitivity.SECRET or f.sensitive:
            refused_secret += 1
            continue  # never read/keep a secret, even if a value was sent
        value = (f.value or "").strip()
        if not value:
            continue
        key = key_for_field(f)
        if not key:
            continue
        pairs.append({"key": key, "value": value, "label": f.label or key})

    result = apply_learned(prof_dict, pairs)
    if result["applied"]:
        store.save_profile(Profile.model_validate(result["profile"]))

    return {
        "learned": result["applied"],
        "skipped": result["skipped"],
        "counts": {
            "learned": len(result["applied"]),
            "skipped": len(result["skipped"]),
            "refused_secret": refused_secret,
        },
    }


_MAX_RESUME_BYTES = 15 * 1024 * 1024


@router.post("/import-resume", dependencies=[Depends(require_token)])
async def import_resume(file: UploadFile = File(...)) -> dict:
    """Populate the ACTIVE profile from an uploaded resume (PDF or text).

    100% local: we extract the resume text (pypdf for PDF), pull out contact
    fields with regex, and fill ONLY empty profile slots (same non-destructive
    rule as 'learn'). Nothing is sent to any LLM or network. Structured history
    (work/education/skills) is left for the user to edit in the profile page.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(data) > _MAX_RESUME_BYTES:
        raise HTTPException(status_code=413, detail="Resume too large (15MB max).")
    try:
        text = extract_text(data, file.filename or "")
    except Exception as e:
        raise HTTPException(status_code=422, detail="Could not read resume: %s" % e)
    if not text.strip():
        raise HTTPException(status_code=422,
                            detail="No readable text found (a scanned image PDF can't be parsed).")

    pairs = extract_facts(text)
    prof_dict = store.get_profile().model_dump()
    result = apply_learned(prof_dict, pairs)
    if result["applied"]:
        store.save_profile(Profile.model_validate(result["profile"]))

    return {
        "found": pairs,
        "imported": result["applied"],
        "skipped": result["skipped"],
        "counts": {
            "found": len(pairs),
            "imported": len(result["applied"]),
            "skipped": len(result["skipped"]),
        },
    }
