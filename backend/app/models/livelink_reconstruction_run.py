from __future__ import annotations

"""Audit record for one history-reconstruction run."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LiveLinkReconstructionRun(Base):
    """One invocation of the session-boundary reconstruction tool.

    Three revisions of the design answered "how does an admin know what
    happened?" with "log it". A log rotates, a container restart loses it, and
    the one question asked afterwards -- what did this change, and what did it
    refuse? -- becomes unanswerable at exactly the moment it matters.

    Refusal is a ROUTINE outcome here, not an exceptional one: the tool requires
    positive evidence of telemetry coverage before it will touch a session, and
    a session straddling the retention horizon legitimately fails that test. In
    a quiet log a safe refusal and a broken tool look identical.

    It also gives the dry run a purpose beyond reassurance: the plan is
    recorded, so an applied run can be compared against what was previewed.
    """

    __tablename__ = "livelink_reconstruction_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    #: What the run was allowed to do, and under which settings. Recorded rather
    #: than inferred, because both are editable between runs.
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    gap_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    boundary_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    sessions_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sessions_merged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sessions_split: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sessions_closed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sessions_refused: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: JSON array of ``{"session_id": int, "reason": str}``. Stored as text
    #: rather than a JSON column so the shape is identical on both dialects;
    #: it is written and read in one place each.
    refusals: Mapped[str | None] = mapped_column(Text)
