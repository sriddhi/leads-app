import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AttorneyRead(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: str
    is_active: bool
    max_open_cases: int
    open: int


class CapacityUpdate(BaseModel):
    max_open_cases: int = Field(..., ge=0, le=1000)


class AutoAssignToggle(BaseModel):
    enabled: bool


class AuditEventRead(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None
    actor_kind: str
    action: str
    before: dict | None = None
    after: dict | None = None
    reason: str | None = None
    ip: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedAudit(BaseModel):
    items: list[AuditEventRead]
    total: int
    page: int
    page_size: int
    pages: int


class MetricsAttorneyRow(BaseModel):
    id: uuid.UUID
    name: str
    open: int
    cap: int
    utilization: float


class MetricsRead(BaseModel):
    queue_depth: int
    oldest_queued_age_seconds: int
    in_progress: int
    reached_out: int
    reached_out_last_hour: int
    attorneys: list[MetricsAttorneyRow]


class AttorneyTimeRow(BaseModel):
    attorney_id: uuid.UUID
    name: str
    total_holding_seconds: int
    cases_handled: int
    avg_time_to_reached_out_seconds: int
    current_open_load: int
    oldest_open_age_seconds: int
