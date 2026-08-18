from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import load_config
from .db import CouncilRound, CouncilSession, Database
from .orchestrator import CouncilOrchestrator, to_session_out
from .schemas import HumanAction, SessionCreate, SessionOut

config = load_config()
Path("data").mkdir(exist_ok=True)
database = Database(config.database_url)
database.create_all()
orchestrator = CouncilOrchestrator(config)

app = FastAPI(title="LLM Expert Group", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    yield from database.session()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/models")
def models() -> dict:
    return {
        "chairman": config.chairman,
        "secretary": config.secretary,
        "experts": config.experts,
        "models": [model.public_dict() for model in config.models],
    }


@app.get("/api/sessions", response_model=list[SessionOut])
def list_sessions(db: Session = Depends(get_db)):
    rows = db.execute(
        select(CouncilSession).options(selectinload(CouncilSession.rounds).selectinload(CouncilRound.secretary_interactions)).order_by(CouncilSession.updated_at.desc())
    ).scalars().all()
    return [to_session_out(row) for row in rows]


@app.post("/api/sessions", response_model=SessionOut)
def create_session(request: SessionCreate, db: Session = Depends(get_db)):
    try:
        return to_session_out(orchestrator.create_session(db, request))
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: str, db: Session = Depends(get_db)):
    try:
        return to_session_out(orchestrator._load(db, session_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc


@app.post("/api/sessions/{session_id}/rounds/run", response_model=SessionOut)
async def run_round(session_id: str, db: Session = Depends(get_db)):
    try:
        return to_session_out(await orchestrator.run_next_round(db, session_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/action", response_model=SessionOut)
async def human_action(session_id: str, request: HumanAction, db: Session = Depends(get_db)):
    try:
        return to_session_out(await orchestrator.apply_human_action(db, session_id, request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
