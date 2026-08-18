from pathlib import Path

import pytest
from sqlalchemy import select

from app.adapters import ModelAdapter
from app.config import AppConfig, ModelConfig
from app.db import CouncilRoundEvent, Database
from app.orchestrator import CouncilOrchestrator, to_round_run_out
from app.schemas import SessionCreate


class StreamingFakeAdapter(ModelAdapter):
    async def generate(self, *, system: str, prompt: str) -> str:
        if self.config.id == "chair" and "Synthesize council round" in prompt:
            return '{"action":"final","content":"# Synthesis"}'
        if self.config.id == "chair":
            return '{"action":"final","content":"# Opening"}'
        return '{"action":"final","content":"# Recommendation\\nProceed"}'


class FailingSynthesisAdapter(StreamingFakeAdapter):
    async def generate(self, *, system: str, prompt: str) -> str:
        if self.config.id == "chair" and "Synthesize council round" in prompt:
            raise TimeoutError("chairman synthesis timed out")
        return await super().generate(system=system, prompt=prompt)


class EmptyAfterSecretaryAdapter(StreamingFakeAdapter):
    async def generate(self, *, system: str, prompt: str) -> str:
        if self.config.id == "chair" and "SECRETARY ANSWER #1" in prompt:
            if "previous reply did not contain" in prompt:
                return '{"action":"final","content":"# Recovered opening"}'
            return ""
        if self.config.id == "chair":
            return '{"action":"ask_secretary","question":"What does the repository contain?"}'
        return await super().generate(system=system, prompt=prompt)


def make_config(tmp_path: Path) -> AppConfig:
    models = [
        ModelConfig(id="chair", display_name="Chair", protocol="openai_responses", model="x", api_url="https://x", api_key="x"),
        ModelConfig(id="secretary", display_name="Secretary", protocol="openai_responses", model="x", api_url="https://x", api_key="x"),
        ModelConfig(id="expert", display_name="Expert", protocol="openai_responses", model="x", api_url="https://x", api_key="x"),
    ]
    return AppConfig(chairman="chair", secretary="secretary", experts=["expert"], models=models, database_url=f"sqlite:///{tmp_path / 'council.db'}", langgraph_checkpoint_path=str(tmp_path / "graph.sqlite"))


@pytest.mark.asyncio
async def test_streamed_round_persists_events_and_finishes_at_human_gate(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("project", encoding="utf-8")
    config = make_config(tmp_path)
    database = Database(config.database_url)
    database.create_all()
    orchestrator = CouncilOrchestrator(config, adapter_factory=lambda cfg: StreamingFakeAdapter(cfg), session_factory=database.SessionLocal)
    db = database.SessionLocal()
    session = orchestrator.create_session(db, SessionCreate(title="t", topic="question", repo_path=str(repo)))
    run = orchestrator.start_round_run(db, session.id)
    db.close()

    await orchestrator.execute_round_run(run.id)

    db = database.SessionLocal()
    stored = orchestrator._load_run(db, run.id)
    event_types = db.execute(select(CouncilRoundEvent.event_type).where(CouncilRoundEvent.run_id == run.id).order_by(CouncilRoundEvent.sequence)).scalars().all()
    session = orchestrator._load(db, session.id)
    assert to_round_run_out(stored).status == "awaiting_human"
    assert session.status == "awaiting_human"
    assert session.rounds[0].opening_statement == "# Opening"
    assert "chairman.delta" in event_types
    assert "chairman.secretary.started" in event_types
    assert "chairman.secretary.completed" in event_types
    assert "expert.delta" in event_types
    assert "synthesis.delta" in event_types
    assert event_types[-1] == "human_gate"
    db.close()


@pytest.mark.asyncio
async def test_synthesis_failure_keeps_opening_experts_and_replayable_events(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("project", encoding="utf-8")
    config = make_config(tmp_path)
    database = Database(config.database_url)
    database.create_all()
    orchestrator = CouncilOrchestrator(config, adapter_factory=lambda cfg: FailingSynthesisAdapter(cfg), session_factory=database.SessionLocal)
    db = database.SessionLocal()
    session = orchestrator.create_session(db, SessionCreate(title="t", topic="question", repo_path=str(repo)))
    run = orchestrator.start_round_run(db, session.id)
    db.close()

    await orchestrator.execute_round_run(run.id)

    db = database.SessionLocal()
    stored = orchestrator._load_run(db, run.id)
    events = db.execute(select(CouncilRoundEvent.event_type).where(CouncilRoundEvent.run_id == run.id).order_by(CouncilRoundEvent.sequence)).scalars().all()
    session = orchestrator._load(db, session.id)
    output = to_round_run_out(stored)
    assert output.status == "failed"
    assert output.opening_statement == "# Opening"
    assert output.expert_responses[0].content == "# Recommendation\nProceed"
    assert output.error == "TimeoutError: chairman synthesis timed out"
    assert "expert.completed" in events
    assert events[-1] == "round.failed"
    assert session.status == "error"
    assert session.rounds == []
    db.close()


@pytest.mark.asyncio
async def test_empty_chairman_reply_after_secretary_gets_one_corrective_retry(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("project", encoding="utf-8")
    config = make_config(tmp_path)
    database = Database(config.database_url)
    database.create_all()
    orchestrator = CouncilOrchestrator(config, adapter_factory=lambda cfg: EmptyAfterSecretaryAdapter(cfg), session_factory=database.SessionLocal)
    db = database.SessionLocal()
    session = orchestrator.create_session(db, SessionCreate(title="t", topic="question", repo_path=str(repo)))
    run = orchestrator.start_round_run(db, session.id)
    db.close()

    await orchestrator.execute_round_run(run.id)

    db = database.SessionLocal()
    stored = orchestrator._load_run(db, run.id)
    session = orchestrator._load(db, session.id)
    assert stored.status == "awaiting_human"
    assert stored.opening_statement == "# Recovered opening"
    opening_sequences = [
        item.sequence
        for item in session.rounds[0].secretary_interactions
        if item.requester_role == "chairman" and item.phase == "opening"
    ]
    assert opening_sequences == [1, 2]
    db.close()


def test_stop_active_round_marks_run_and_session_stopped(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("project", encoding="utf-8")
    config = make_config(tmp_path)
    database = Database(config.database_url)
    database.create_all()
    orchestrator = CouncilOrchestrator(config, adapter_factory=lambda cfg: StreamingFakeAdapter(cfg), session_factory=database.SessionLocal)
    db = database.SessionLocal()
    session = orchestrator.create_session(db, SessionCreate(title="t", topic="question", repo_path=str(repo)))
    run = orchestrator.start_round_run(db, session.id)

    stopped = orchestrator.stop_active_round_run(db, session.id)

    assert stopped is not None
    assert stopped.id == run.id
    assert stopped.status == "stopped"
    assert stopped.error == "Stopped by user."
    assert orchestrator._load(db, session.id).status == "stopped"
    events = db.execute(select(CouncilRoundEvent.event_type).where(CouncilRoundEvent.run_id == run.id).order_by(CouncilRoundEvent.sequence)).scalars().all()
    assert events[-1] == "round.stopped"
    db.close()


def test_restart_recovery_marks_unfinished_round_retryable(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("project", encoding="utf-8")
    config = make_config(tmp_path)
    database = Database(config.database_url)
    database.create_all()
    orchestrator = CouncilOrchestrator(config, adapter_factory=lambda cfg: StreamingFakeAdapter(cfg), session_factory=database.SessionLocal)
    db = database.SessionLocal()
    session = orchestrator.create_session(db, SessionCreate(title="t", topic="question", repo_path=str(repo)))
    run = orchestrator.start_round_run(db, session.id)

    assert orchestrator.recover_interrupted_round_runs(db) == 1

    assert orchestrator._load_run(db, run.id).status == "failed"
    assert "Backend restarted" in (orchestrator._load_run(db, run.id).error or "")
    assert orchestrator._load(db, session.id).status == "error"
    events = db.execute(select(CouncilRoundEvent.event_type).where(CouncilRoundEvent.run_id == run.id).order_by(CouncilRoundEvent.sequence)).scalars().all()
    assert events[-1] == "round.failed"
    db.close()
