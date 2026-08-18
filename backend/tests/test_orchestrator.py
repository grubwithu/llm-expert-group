from pathlib import Path

import pytest

from app.adapters import ModelAdapter
from app.config import AppConfig, ModelConfig
from app.db import Database
from app.orchestrator import CouncilOrchestrator
from app.schemas import HumanAction, SessionCreate


class FakeAdapter(ModelAdapter):
    async def generate(self, *, system: str, prompt: str) -> str:
        if "Prepare the neutral opening statement" in prompt:
            return "# Opening\nNeutral agenda"
        if "Synthesize council round" in prompt:
            return "# Summary\nDisagreement D1"
        return f"# Recommendation\nfrom {self.config.id}"


@pytest.mark.asyncio
async def test_human_gate_and_second_round(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("project", encoding="utf-8")
    models = [
        ModelConfig(id="chair", display_name="Chair", protocol="openai_responses", model="x", api_url="https://x", api_key="x"),
        ModelConfig(id="a", display_name="A", protocol="openai_responses", model="x", api_url="https://x", api_key="x"),
        ModelConfig(id="b", display_name="B", protocol="anthropic_messages", model="x", api_url="https://x", api_key="x"),
    ]
    config = AppConfig(chairman="chair", experts=["a", "b"], models=models, database_url=f"sqlite:///{tmp_path/'test.db'}")
    dbm = Database(config.database_url)
    dbm.create_all()
    orchestrator = CouncilOrchestrator(config, adapter_factory=lambda cfg: FakeAdapter(cfg))
    db = dbm.SessionLocal()
    item = orchestrator.create_session(db, SessionCreate(title="t", topic="question", repo_path=str(repo)))
    item = await orchestrator.run_next_round(db, item.id)
    assert item.status == "awaiting_human"
    assert item.current_round == 1
    item = orchestrator.apply_human_action(db, item.id, HumanAction(action="continue"))
    assert item.status == "ready"
    item = await orchestrator.run_next_round(db, item.id)
    assert item.current_round == 2
    assert item.status == "awaiting_human"


@pytest.mark.asyncio
async def test_cannot_advance_without_human_action(tmp_path: Path):
    repo = tmp_path / "repo2"
    repo.mkdir()
    (repo / "README.md").write_text("project", encoding="utf-8")
    models = [
        ModelConfig(id="chair", display_name="Chair", protocol="openai_responses", model="x", api_url="https://x", api_key="x"),
        ModelConfig(id="a", display_name="A", protocol="openai_responses", model="x", api_url="https://x", api_key="x"),
    ]
    config = AppConfig(chairman="chair", experts=["a"], models=models, database_url=f"sqlite:///{tmp_path/'gate.db'}")
    dbm = Database(config.database_url)
    dbm.create_all()
    orchestrator = CouncilOrchestrator(config, adapter_factory=lambda cfg: FakeAdapter(cfg))
    db = dbm.SessionLocal()
    item = orchestrator.create_session(db, SessionCreate(title="t", topic="question", repo_path=str(repo)))
    item = await orchestrator.run_next_round(db, item.id)
    with pytest.raises(ValueError, match="human action"):
        await orchestrator.run_next_round(db, item.id)
