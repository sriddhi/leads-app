import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    lead_number: Mapped[str | None] = mapped_column(
        String(50), unique=True, nullable=True
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    normalized_phone: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    resume_original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="PENDING",
        default="PENDING",
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="1",
        default=1,
    )
    submitter_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_potential_duplicate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Atomic optimistic locking, enforced at the database — NOT just in application
    # memory. SQLAlchemy appends `AND version = :loaded_version` to every UPDATE/DELETE
    # for this row, increments the column itself, and raises StaleDataError when the
    # predicate matches 0 rows (i.e. another transaction changed the row first). This is
    # the compare-and-swap that makes "no double-assign, no lost updates" actually true
    # under concurrency. Because SQLAlchemy owns this column, application code must NEVER
    # increment `version` by hand — doing so corrupts the managed value.
    __mapper_args__ = {"version_id_col": version}

    def __repr__(self) -> str:
        return f"<Lead id={self.id} email={self.email} status={self.status}>"
