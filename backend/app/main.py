from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.database import get_db, init_db
from backend.app.models import Collaborator, Cycle, TimesheetRecord
from backend.app.services.ingestion import ingest_file

log = logging.getLogger(__name__)

app = FastAPI(
    title="PMAS API",
    description="Project Management Assistant System — Timesheet Foundation",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    log.info("PMAS API pronta. Banco inicializado.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

DbSession = Annotated[Session, Depends(get_db)]


@app.post("/api/upload-timesheet", summary="Ingerir CSV de timesheet")
def upload_timesheet(file: UploadFile, db: DbSession):
    """
    Recebe um arquivo CSV de timesheet e persiste os registros.
    Ciclos de Quarentena são criados automaticamente para datas órfãs.
    """
    fname = file.filename or ""
    if not any(fname.lower().endswith(ext) for ext in (".csv", ".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Apenas arquivos .csv ou .xlsx são aceitos.")

    contents = file.file.read()
    try:
        summary = ingest_file(contents, fname, db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("Erro inesperado durante ingestão do CSV.")
        raise HTTPException(status_code=500, detail="Erro interno durante ingestão.") from exc

    return {"status": "ok", **summary}


@app.get("/api/cycles", summary="Listar ciclos")
def list_cycles(db: DbSession):
    """Retorna todos os ciclos ordenados por data de início."""
    cycles = db.query(Cycle).order_by(Cycle.start_date).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "start_date": c.start_date.isoformat(),
            "end_date": c.end_date.isoformat(),
            "is_quarantine": c.is_quarantine,
        }
        for c in cycles
    ]


@app.get("/api/dashboard/{cycle_id}", summary="Dashboard de horas por ciclo")
def get_dashboard(cycle_id: int, db: DbSession):
    """
    Retorna horas agregadas por colaborador para o ciclo solicitado.
    O agrupamento é feito via SQL (GROUP BY collaborator_id) para minimizar
    o tráfego de rede.
    """
    cycle = db.get(Cycle, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="Ciclo não encontrado.")

    rows = (
        db.query(
            Collaborator.name.label("collaborator"),
            func.sum(TimesheetRecord.normal_hours).label("normal_hours"),
            func.sum(TimesheetRecord.extra_hours).label("extra_hours"),
            func.sum(TimesheetRecord.standby_hours).label("standby_hours"),
        )
        .join(Collaborator, TimesheetRecord.collaborator_id == Collaborator.id)
        .filter(TimesheetRecord.cycle_id == cycle_id)
        .group_by(TimesheetRecord.collaborator_id)
        .order_by(Collaborator.name)
        .all()
    )

    return {
        "cycle": {
            "id": cycle.id,
            "name": cycle.name,
            "start_date": cycle.start_date.isoformat(),
            "end_date": cycle.end_date.isoformat(),
            "is_quarantine": cycle.is_quarantine,
        },
        "data": [
            {
                "collaborator": r.collaborator,
                "normal_hours": r.normal_hours or 0.0,
                "extra_hours": r.extra_hours or 0.0,
                "standby_hours": r.standby_hours or 0.0,
            }
            for r in rows
        ],
    }
