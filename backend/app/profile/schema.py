"""Profile data models — JSON Resume-inspired, plus job-application fields.

IMPORTANT: no secrets ever live here. Passwords, OTP/2FA, CAPTCHA, card/CVV/PIN,
bank logins and SSN are handled by the extension's manual-entry passthrough and
are never stored in the profile.
"""
from typing import List, Optional

from pydantic import BaseModel, Field


class Location(BaseModel):
    address: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None       # state / province
    postal_code: Optional[str] = None
    country: Optional[str] = None


class SocialProfile(BaseModel):
    network: str = ""                  # e.g. "LinkedIn", "GitHub"
    username: Optional[str] = None
    url: Optional[str] = None


class Basics(BaseModel):
    name: Optional[str] = None
    headline: Optional[str] = None     # e.g. "Backend Engineer"
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    summary: Optional[str] = None
    location: Location = Field(default_factory=Location)
    profiles: List[SocialProfile] = Field(default_factory=list)


class WorkItem(BaseModel):
    company: Optional[str] = None
    position: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[str] = None   # free-form: "2022-01", "Jan 2022"
    end_date: Optional[str] = None     # or "Present"
    summary: Optional[str] = None
    highlights: List[str] = Field(default_factory=list)


class EducationItem(BaseModel):
    institution: Optional[str] = None
    area: Optional[str] = None         # field of study
    study_type: Optional[str] = None   # degree, e.g. "B.Tech"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    score: Optional[str] = None        # GPA / percentage
    courses: List[str] = Field(default_factory=list)


class SkillItem(BaseModel):
    name: str = ""
    level: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)


class ProjectItem(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    highlights: List[str] = Field(default_factory=list)


class JobPreferences(BaseModel):
    work_authorization: Optional[str] = None   # e.g. "Indian citizen", "US - needs H-1B"
    requires_sponsorship: Optional[bool] = None
    desired_salary: Optional[str] = None
    salary_currency: Optional[str] = None
    notice_period: Optional[str] = None
    earliest_start_date: Optional[str] = None
    willing_to_relocate: Optional[bool] = None
    preferred_locations: List[str] = Field(default_factory=list)
    work_mode: Optional[str] = None             # remote / hybrid / onsite
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None


class VoluntaryDisclosures(BaseModel):
    """Optional EEO answers some applications request. Leave blank to skip —
    nothing here is required, and it is only ever used to answer a matching
    voluntary question on a form."""
    gender: Optional[str] = None
    race_ethnicity: Optional[str] = None
    hispanic_latino: Optional[str] = None
    veteran_status: Optional[str] = None
    disability_status: Optional[str] = None


class Profile(BaseModel):
    basics: Basics = Field(default_factory=Basics)
    work: List[WorkItem] = Field(default_factory=list)
    education: List[EducationItem] = Field(default_factory=list)
    skills: List[SkillItem] = Field(default_factory=list)
    projects: List[ProjectItem] = Field(default_factory=list)
    job_preferences: JobPreferences = Field(default_factory=JobPreferences)
    voluntary: VoluntaryDisclosures = Field(default_factory=VoluntaryDisclosures)
