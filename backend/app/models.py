from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from backend.app.database import Base


class Collaborator(Base):
    __tablename__ = "collaborator"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)

    records: list[TimesheetRecord] = relationship(
        "TimesheetRecord", back_populates="collaborator"
    )


class Cycle(Base):
    __tablename__ = "cycle"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    # True for auto-generated quarantine cycles
    is_quarantine = Column(Boolean, default=False, nullable=False)

    records: list[TimesheetRecord] = relationship(
        "TimesheetRecord", back_populates="cycle"
    )


class TimesheetRecord(Base):
    __tablename__ = "timesheet_record"

    id = Column(Integer, primary_key=True, index=True)
    collaborator_id = Column(Integer, ForeignKey("collaborator.id"), nullable=False)
    cycle_id = Column(Integer, ForeignKey("cycle.id"), nullable=False)
    record_date = Column(Date, nullable=False)
    pep_wbs = Column(String, nullable=True)
    normal_hours = Column(Float, default=0.0, nullable=False)
    extra_hours = Column(Float, default=0.0, nullable=False)
    standby_hours = Column(Float, default=0.0, nullable=False)

    collaborator: Collaborator = relationship(
        "Collaborator", back_populates="records"
    )
    cycle: Cycle = relationship("Cycle", back_populates="records")


# Composite index to speed up dashboard GROUP BY queries
Index(
    "ix_timesheet_cycle_collaborator",
    TimesheetRecord.cycle_id,
    TimesheetRecord.collaborator_id,
)
