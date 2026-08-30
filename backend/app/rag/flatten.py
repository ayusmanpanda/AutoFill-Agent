"""Flatten a nested Profile into a flat list of retrievable facts.

Each fact is a plain dict: {"key", "value", "kind", "hint"}.
  key   canonical id used to match fields and to reference the fact in the LLM catalog
  value the actual string to fill (stays local — never sent to the cloud)
  kind  drives option-matching/formatting (name/email/phone/url/address/.../choice)
  hint  short human description shown to the LLM matcher (no user value in it)

Duck-typed (getattr only) so it works on a Pydantic Profile AND on a plain
SimpleNamespace in tests. Empty values are skipped, so a blank profile yields [].
Pure/stdlib — importable and testable without the web stack.
"""
from typing import Any, Dict, List, Optional


def _g(obj: Any, *path: str) -> Optional[Any]:
    """getattr down a path, tolerant of None along the way."""
    cur = obj
    for p in path:
        if cur is None:
            return None
        cur = getattr(cur, p, None)
    return cur


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def flatten_profile(profile: Any) -> List[Dict[str, str]]:
    facts: List[Dict[str, str]] = []

    def add(key: str, value: Any, kind: str, hint: str) -> None:
        val = _s(value)
        if val:
            facts.append({"key": key, "value": val, "kind": kind, "hint": hint})

    basics = _g(profile, "basics")
    name = _s(_g(basics, "name"))
    add("name", name, "name", "Full name")
    if name:
        parts = name.split()
        if len(parts) >= 2:
            add("given_name", parts[0], "name", "First / given name")
            add("family_name", parts[-1], "name", "Last / family name")
        elif len(parts) == 1:
            add("given_name", parts[0], "name", "First / given name")

    add("email", _g(basics, "email"), "email", "Email address")
    add("phone", _g(basics, "phone"), "phone", "Phone number")
    add("website", _g(basics, "website"), "url", "Personal website")
    add("headline", _g(basics, "headline"), "text", "Professional headline / title")
    add("summary", _g(basics, "summary"), "text", "Professional summary / bio")

    loc = _g(basics, "location")
    add("address", _g(loc, "address"), "address", "Street address")
    add("city", _g(loc, "city"), "city", "City")
    add("region", _g(loc, "region"), "region", "State / region / province")
    add("postal_code", _g(loc, "postal_code"), "postal_code", "Postal / ZIP / PIN code")
    add("country", _g(loc, "country"), "country", "Country")

    # Social/portfolio links: prefer job_preferences, else derive from basics.profiles.
    jp = _g(profile, "job_preferences")
    links = {
        "linkedin": _s(_g(jp, "linkedin")),
        "github": _s(_g(jp, "github")),
        "portfolio": _s(_g(jp, "portfolio")),
    }
    profiles = _g(basics, "profiles") or []
    for pr in profiles:
        net = _s(_g(pr, "network")).lower()
        url = _s(_g(pr, "url"))
        if not url:
            continue
        if "linkedin" in net and not links["linkedin"]:
            links["linkedin"] = url
        elif "github" in net and not links["github"]:
            links["github"] = url
    add("linkedin", links["linkedin"], "url", "LinkedIn profile URL")
    add("github", links["github"], "url", "GitHub profile URL")
    add("portfolio", links["portfolio"], "url", "Portfolio URL")

    # Most-recent work (convention: newest first).
    work = _g(profile, "work") or []
    if work:
        add("current_title", _g(work[0], "position"), "text", "Most recent job title")
        add("current_company", _g(work[0], "company"), "text", "Most recent employer")

    # Most-recent education.
    edu = _g(profile, "education") or []
    if edu:
        add("education_institution", _g(edu[0], "institution"), "text",
            "Most recent school / university")
        degree = " ".join(x for x in (_s(_g(edu[0], "study_type")),
                                       _s(_g(edu[0], "area"))) if x)
        add("education_degree", degree, "text", "Most recent degree / field of study")

    # Skills (comma-joined names).
    skills = _g(profile, "skills") or []
    skill_names = [_s(_g(s, "name")) for s in skills]
    skill_names = [s for s in skill_names if s]
    if skill_names:
        add("skills", ", ".join(skill_names), "list", "Skills (comma-separated)")

    # Job preferences.
    add("work_authorization", _g(jp, "work_authorization"), "text",
        "Work authorization / right to work")
    salary = _s(_g(jp, "desired_salary"))
    if salary:
        cur = _s(_g(jp, "salary_currency"))
        add("desired_salary", (cur + " " + salary).strip() if cur else salary,
            "money", "Desired salary / compensation")
    add("notice_period", _g(jp, "notice_period"), "text", "Notice period")
    add("earliest_start_date", _g(jp, "earliest_start_date"), "date",
        "Earliest start / availability date")
    add("work_mode", _g(jp, "work_mode"), "choice", "Preferred work mode (remote/hybrid/onsite)")

    # Yes/No preferences (only when explicitly set — None means "unknown", skip).
    for key, attr, hint in (
        ("requires_sponsorship", "requires_sponsorship", "Requires visa sponsorship (yes/no)"),
        ("willing_to_relocate", "willing_to_relocate", "Willing to relocate (yes/no)"),
    ):
        b = _g(jp, attr)
        if isinstance(b, bool):
            add(key, "Yes" if b else "No", "choice", hint)

    # Voluntary EEO answers (only used to answer a matching voluntary question).
    vol = _g(profile, "voluntary")
    add("gender", _g(vol, "gender"), "choice", "Gender (voluntary)")
    add("race_ethnicity", _g(vol, "race_ethnicity"), "choice", "Race / ethnicity (voluntary)")
    add("veteran_status", _g(vol, "veteran_status"), "choice", "Veteran status (voluntary)")
    add("disability_status", _g(vol, "disability_status"), "choice",
        "Disability status (voluntary)")

    return facts


def facts_by_key(facts: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    return {f["key"]: f for f in facts}


def key_catalog(facts: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """The catalog handed to the LLM matcher: keys + kind + hint, NEVER values."""
    return [{"key": f["key"], "kind": f["kind"], "hint": f["hint"]} for f in facts]
