from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import load_config
from .db import CouncilRound, CouncilRoundEvent, CouncilRoundRun, CouncilSession, Database
from .orchestrator import CouncilOrchestrator, to_round_run_out, to_session_out
from .schemas import HumanAction, RoundRunOut, SessionCreate, SessionOut

config = load_config()
Path("data").mkdir(exist_ok=True)
database = Database(config.database_url)
database.create_all()
orchestrator = CouncilOrchestrator(config, session_factory=database.SessionLocal)
with database.SessionLocal() as recovery_db:
    orchestrator.recover_interrupted_round_runs(recovery_db)
round_tasks: dict[str, asyncio.Task[None]] = {}

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
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="The synchronous round endpoint was retired. Start a background streamed round with POST /api/sessions/{session_id}/rounds.",
    )


@app.post("/api/sessions/{session_id}/rounds", response_model=RoundRunOut, status_code=status.HTTP_202_ACCEPTED)
async def start_round(session_id: str, db: Session = Depends(get_db)):
    """Start a round in the background; subscribe to its SSE feed for progress."""
    try:
        run = orchestrator.start_round_run(db, session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    task = asyncio.create_task(orchestrator.execute_round_run(run.id))
    round_tasks[run.id] = task
    task.add_done_callback(lambda completed: round_tasks.pop(run.id, None))
    return to_round_run_out(run)


@app.post("/api/sessions/{session_id}/rounds/stop", response_model=RoundRunOut | None)
async def stop_round(session_id: str, db: Session = Depends(get_db)):
    """Cancel every in-flight model call for this session's active round."""
    try:
        # The executor publishes events under the same lock.  Serializing this
        # stop transition prevents duplicate/out-of-order SSE sequence values.
        async with orchestrator._event_lock:
            run = orchestrator.stop_active_round_run(db, session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc

    if run is not None:
        task = round_tasks.get(run.id)
        if task is not None and not task.done():
            task.cancel()
        return to_round_run_out(run)
    return None


@app.get("/api/round-runs/{run_id}", response_model=RoundRunOut)
def get_round_run(run_id: str, db: Session = Depends(get_db)):
    try:
        return to_round_run_out(orchestrator._load_run(db, run_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="round run not found") from exc


@app.get("/api/sessions/{session_id}/round-runs/latest", response_model=RoundRunOut | None)
def get_latest_round_run(session_id: str, db: Session = Depends(get_db)):
    try:
        orchestrator._load(db, session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    run = orchestrator.latest_round_run(db, session_id)
    return to_round_run_out(run) if run else None


@app.get("/api/round-runs/{run_id}/events")
async def stream_round_events(run_id: str, request: Request, after: int = 0):
    async def events():
        try:
            reconnect_after = int(request.headers.get("last-event-id", "0"))
        except ValueError:
            reconnect_after = 0
        # EventSource sends Last-Event-ID on reconnect.  Without honoring it,
        # every reconnect replays prior deltas and duplicates streamed prose.
        cursor = max(0, after, reconnect_after)
        while True:
            db = database.SessionLocal()
            try:
                run = db.get(CouncilRoundRun, run_id)
                if run is None:
                    yield "event: council\ndata: " + json.dumps({"type": "round.failed", "payload": {"error": "round run not found"}}) + "\n\n"
                    return
                rows = db.execute(
                    select(CouncilRoundEvent)
                    .where(CouncilRoundEvent.run_id == run_id, CouncilRoundEvent.sequence > cursor)
                    .order_by(CouncilRoundEvent.sequence)
                ).scalars().all()
                terminal = run.status in {"awaiting_human", "failed", "stopped"}
            finally:
                db.close()
            for row in rows:
                cursor = row.sequence
                data = json.dumps({"type": row.event_type, "payload": json.loads(row.payload_json)}, ensure_ascii=False)
                yield f"id: {row.sequence}\nevent: council\ndata: {data}\n\n"
            if terminal and not rows:
                return
            if await request.is_disconnected():
                return
            await asyncio.sleep(0.25)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
