import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, field_validator


class LeadCreate(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr

    @field_validator("first_name", "last_name")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Field cannot be blank")
        return v


class LeadRead(BaseModel):
    id: uuid.UUID
    lead_number: str | None = None
    first_name: str
    last_name: str
    email: str
    phone: str | None = None
    message: str | None = None
    resume_filename: str
    resume_original_filename: str
    status: str
    assignee_id: uuid.UUID | None = None
    assignee_name: str | None = None
    version: int
    is_potential_duplicate: bool = False
    duplicate_of: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeadReceipt(BaseModel):
    """Minimal public confirmation returned from the public submit endpoint.

    Deliberately excludes all internal fields (assignee, version, dedup linkage, IP) so the
    public channel can't be used to enumerate or read back internal/other-user data.
    """
    lead_number: str | None = None
    status: str
    message: str = "Your application has been received."


class LeadStatusUpdate(BaseModel):
    status: Literal["REACHED_OUT"]
    version: int


class StatePeriodRead(BaseModel):
    id: uuid.UUID
    state: str
    assignee_id: uuid.UUID | None = None
    entered_at: datetime
    exited_at: datetime | None = None
    duration_seconds: int | None = None

    model_config = {"from_attributes": True}


class LeadDetail(LeadRead):
    timeline: list[StatePeriodRead] = []


class QueueItem(BaseModel):
    id: uuid.UUID
    lead_number: str | None = None
    first_name: str
    last_name: str
    email: str
    status: str
    assignee_id: uuid.UUID | None = None
    version: int
    is_potential_duplicate: bool = False
    created_at: datetime
    age_seconds: int


class AssignRequest(BaseModel):
    version: int


class ReassignRequest(BaseModel):
    version: int
    assignee_id: uuid.UUID | None = None
    reason: str | None = None


class ReverseRequest(BaseModel):
    version: int
    reason: str

    @field_validator("reason")
    @classmethod
    def reason_required(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("A reason is required to reverse a lead.")
        return v


class PaginatedLeads(BaseModel):
    items: list[LeadRead]
    total: int
    page: int
    page_size: int
    pages: int


class CaseHistoryItem(BaseModel):
    """A prior case surfaced in a lead's case-history view."""
    id: uuid.UUID
    lead_number: str | None = None
    first_name: str
    last_name: str
    email: str
    phone: str | None = None
    status: str
    created_at: datetime
    matched_on: list[str] = []


class RelatedLeadItem(BaseModel):
    """An open lead in the same duplicate cluster, eligible for a bulk transition."""
    id: uuid.UUID
    lead_number: str | None = None
    first_name: str
    last_name: str
    email: str
    phone: str | None = None
    status: str
    assignee_id: uuid.UUID | None = None
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}


class RelatedTransitionRequest(BaseModel):
    """Apply one action to selected open related (duplicate-cluster) leads.

    `action`:
      - `assign`       -> self-assign each selected lead to the caller (capacity-checked).
      - `reached_out`  -> mark each selected lead REACHED_OUT (must already be assigned to caller
                          unless caller is admin).
    Each transition records an audit note referencing the parent case number.
    """
    action: Literal["assign", "reached_out"]
    lead_ids: list[uuid.UUID]
    note: str | None = None

    @field_validator("lead_ids")
    @classmethod
    def non_empty(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        if not v:
            raise ValueError("Select at least one related lead.")
        if len(v) > 50:
            raise ValueError("Too many leads selected at once (max 50).")
        return v


class RelatedTransitionResult(BaseModel):
    """Per-lead outcome of a bulk related-transition request."""
    id: uuid.UUID
    lead_number: str | None = None
    ok: bool
    detail: str
