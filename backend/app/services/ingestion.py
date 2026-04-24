from __future__ import annotations

import logging
from datetime import date, timedelta
from io import BytesIO

import pandas as pd
from sqlalchemy.orm import Session

from backend.app.models import Collaborator, Cycle, TimesheetRecord

log = logging.getLogger(__name__)

# Supported column names (the file may have any of these for the PEP/WBS field)
_COL_COLLABORATOR = "Colaborador"
_COL_DATE = "Data"
_COL_HOURS = "Horas totais (decimal)"
_COL_EXTRA = "Hora extra"
_COL_STANDBY = "Hora sobreaviso"
# PEP/WBS: accept "Código PEP" (XLSX export) or legacy "PEP/WBS" (CSV)
_COL_PEP_CANDIDATES = ["Código PEP", "PEP/WBS", "PEP"]

# The column "Ciclo" is intentionally ignored per the Golden Rule.


def ingest_file(file_bytes: bytes, filename: str, db: Session) -> dict:
    """
    Parse a timesheet file (CSV or XLSX), resolve collaborators and cycles,
    and persist TimesheetRecord rows.  Returns a summary dict with counts.
    """
    df = _load_dataframe(file_bytes, filename)
    pep_col = next((c for c in _COL_PEP_CANDIDATES if c in df.columns), None)

    inserted = 0
    quarantine_cycles_created = 0

    for _, row in df.iterrows():
        collab = _get_or_create_collaborator(db, str(row[_COL_COLLABORATOR]).strip())
        record_date: date = _parse_date(row[_COL_DATE])
        cycle, created = _resolve_cycle(db, record_date)
        if created:
            quarantine_cycles_created += 1

        normal_h = 0.0
        extra_h = 0.0
        standby_h = 0.0
        total_h = float(row[_COL_HOURS])

        is_extra = _is_yes(row.get(_COL_EXTRA, ""))
        is_standby = _is_yes(row.get(_COL_STANDBY, ""))

        if is_extra:
            extra_h = total_h
        elif is_standby:
            standby_h = total_h
        else:
            normal_h = total_h

        pep = str(row[pep_col]).strip() if pep_col else None

        record = TimesheetRecord(
            collaborator_id=collab.id,
            cycle_id=cycle.id,
            record_date=record_date,
            pep_wbs=pep,
            normal_hours=normal_h,
            extra_hours=extra_h,
            standby_hours=standby_h,
        )
        db.add(record)
        inserted += 1

    db.commit()
    log.info(
        "Ingestão concluída: %d registros inseridos, %d ciclos de quarentena criados.",
        inserted,
        quarantine_cycles_created,
    )
    return {
        "records_inserted": inserted,
        "quarantine_cycles_created": quarantine_cycles_created,
    }


# Keep backward-compat alias
def ingest_csv(file_bytes: bytes, db: Session) -> dict:
    return ingest_file(file_bytes, "file.csv", db)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _load_dataframe(file_bytes: bytes, filename: str) -> pd.DataFrame:
    name_lower = filename.lower()
    if name_lower.endswith(".xlsx") or name_lower.endswith(".xls"):
        df = pd.read_excel(BytesIO(file_bytes))
    else:
        df = pd.read_csv(BytesIO(file_bytes))

    df.columns = [c.strip() for c in df.columns]
    required = {_COL_COLLABORATOR, _COL_DATE, _COL_HOURS}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Colunas obrigatórias ausentes: {missing}")
    return df


def _get_or_create_collaborator(db: Session, name: str) -> Collaborator:
    collab = db.query(Collaborator).filter(Collaborator.name == name).first()
    if collab is None:
        collab = Collaborator(name=name)
        db.add(collab)
        db.flush()  # obtain id without committing the transaction
    return collab


def _resolve_cycle(db: Session, record_date: date) -> tuple[Cycle, bool]:
    """
    Return the Cycle whose range contains record_date.
    If none exists, create a quarantine cycle for that month.
    Returns (cycle, was_created).
    """
    cycle = (
        db.query(Cycle)
        .filter(Cycle.start_date <= record_date, Cycle.end_date >= record_date)
        .first()
    )
    if cycle is not None:
        return cycle, False

    # Build quarantine cycle spanning the full calendar month of record_date
    start = record_date.replace(day=1)
    # Last day of the month: first day of next month minus one day
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)

    month_label = record_date.strftime("%b/%Y")
    name = f"Quarentena - {month_label}"

    quarantine = Cycle(
        name=name,
        start_date=start,
        end_date=end,
        is_quarantine=True,
    )
    db.add(quarantine)
    db.flush()
    log.warning(
        "Ciclo de quarentena criado: '%s' (datas órfãs em %s não pertencem a nenhum ciclo).",
        name,
        record_date,
    )
    return quarantine, True


def _parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return pd.to_datetime(str(value), dayfirst=True).date()


def _is_yes(value) -> bool:
    return str(value).strip().lower() in {"sim", "yes", "s", "y", "true", "1"}
