"""Normalized 'perceived form' contract.

The browser extension reads a page's fields into this shape and sends it to the
backend. Phase 2 only validates and summarizes it; Phase 4 will match these
fields against the user's profile. Kept deliberately permissive (extra="ignore")
so a slightly richer payload from the extension never 422s.
"""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class FieldOption(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: Optional[str] = None
    label: Optional[str] = None


class PerceivedField(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field_id: str                        # stable id assigned by the scanner, e.g. "f3"
    selector: str                        # CSS selector to re-find the element
    type: str                            # normalized: text/email/tel/select/radio/…
    label: Optional[str] = None          # best resolved human label
    label_source: Optional[str] = None   # how the label was found (debugging)
    name: Optional[str] = None
    dom_id: Optional[str] = None
    autocomplete: Optional[str] = None
    placeholder: Optional[str] = None
    required: bool = False
    group: Optional[str] = None          # fieldset legend / group question
    options: List[FieldOption] = Field(default_factory=list)  # select/radio choices
    max_length: Optional[int] = None     # char limit if the control declares one
    sensitive: bool = False              # secret → never auto-filled, manual only
    sensitive_reason: Optional[str] = None


class PerceivedForm(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: Optional[str] = None
    title: Optional[str] = None
    fields: List[PerceivedField] = Field(default_factory=list)
