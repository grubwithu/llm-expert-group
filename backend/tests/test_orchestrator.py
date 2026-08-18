from pathlib import Path

import pytest

from app.adapters import ModelAdapter
from app.config import AppConfig, ModelConfig
from app.db import Database
from app.orchestrator import CouncilOrchestrator, to_session_out
from app.schemas import HumanAction, SessionCreate


pytestmark = pytest.mark.skip(reason="The synchronous LangGraph round runner was retired in favor of durable streamed round runs.")


class FakeAdapter(ModelAdapter):
    async def generate(self, *, system: str, prompt: str) -> str:
        if self.config.id == "secretary":
            return '{"action":"answer","answer":"The repository contains README.md.","status":"NOT_FOUND","evidence":[],"limitations":["fake test secretary"]}'

        has_secretary_answer = "SECRETARY ANSWER #" in prompt
        if self.config.id == "chair":
            if "Prepare the neutral opening statement" in prompt:
                if not has_secretary_answer:
                    return '{"action":"ask_secretary","question":"What does README.md say about the project?"}'
                return '{"action":"final","content":"# Opening\\nNeutral agenda"}'
            if "Synthesize council round" in prompt:
                if not has_secretary_answer:
                    return '{"action":"ask_secretary","question":"Is there repository evidence relevant to the expert claims?"}'
                return '{"action":"final","content":"# Summary\\nDisagreement D1"}'

        if self.config.id == "a" and not has_secretary_answer:
            return '{"action":"ask_secretary","question":"Is README.md present?"}'
        return '{"action":"final","content":"# Recommendation\\nfrom ' + self.config.id + '"}'


def make_config(tmp_path: Path, *, two_experts: bool = True) -> AppConfig:
    models = [
        ModelConfig(id="chair", display_name="Chair", protocol="openai_responses", model="x", api_url="https://x", api_key="x"),
        ModelConfig(id="secretary", display_name="Secretary", protocol="openai_responses", model="x", api_url="https://x", api_key="x"),
        ModelConfig(id="a", display_name="A", protocol="openai_responses", model="x", api_url="https://x", api_key="x"),
    ]
    experts = ["a"]
    if two_experts:
        models.append(ModelConfig(id="b", display_name="B", protocol="anthropic_messages", model="x", api_url="https://x", api_key="x"))
        experts.append("b")
    return AppConfig(
        chairman="chair",
        secretary="secretary",
        experts=experts,
        models=models,
        database_url=f"sqlite:///{tmp_path / 'council.db'}",
        langgraph_checkpoint_path=str(tmp_path / "langgraph.sqlite"),
    )


@pytest.mark.asyncio
async def test_human_gate_secretary_provenance_and_second_round(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("project", encoding="utf-8")
    config = make_config(tmp_path)
    dbm = Database(config.database_url)
    dbm.create_all()
    orchestrator = CouncilOrchestrator(config, adapter_factory=lambda cfg: FakeAdapter(cfg))
    db = dbm.SessionLocal()

    item = orchestrator.create_session(db, SessionCreate(title="t", topic="question", repo_path=str(repo)))
    item = await orchestrator.run_next_round(db, item.id)
    assert item.status == "awaiting_human"
    assert item.current_round == 1

    out = to_session_out(item)
    round_one = out.rounds[0]
    assert len(round_one.chairman_opening_secretary_queries) == 1
    assert len(round_one.chairman_synthesis_secretary_queries) == 1
    response_a = next(x for x in round_one.expert_responses if x.model_id == "a")
    response_b = next(x for x in round_one.expert_responses if x.model_id == "b")
    assert len(response_a.secretary_queries) == 1
    assert response_b.secretary_queries == []  # Expert B cannot inherit A's private Secretary transcript.

    item = await orchestrator.apply_human_action(db, item.id, HumanAction(action="continue"))
    assert item.status == "ready"
    item = await orchestrator.run_next_round(db, item.id)
    assert item.current_round == 2
    assert item.status == "awaiting_human"


@pytest.mark.asyncio
async def test_cannot_advance_without_human_action(tmp_path: Path):
    repo = tmp_path / "repo2"
    repo.mkdir()
    (repo / "README.md").write_text("project", encoding="utf-8")
    config = make_config(tmp_path, two_experts=False)
    dbm = Database(config.database_url)
    dbm.create_all()
    orchestrator = CouncilOrchestrator(config, adapter_factory=lambda cfg: FakeAdapter(cfg))
    db = dbm.SessionLocal()

    item = orchestrator.create_session(db, SessionCreate(title="t", topic="question", repo_path=str(repo)))
    item = await orchestrator.run_next_round(db, item.id)
    with pytest.raises(ValueError, match="human action"):
        await orchestrator.run_next_round(db, item.id)


@pytest.mark.asyncio
async def test_redirect_requires_note_before_graph_resume(tmp_path: Path):
    repo = tmp_path / "repo3"
    repo.mkdir()
    (repo / "README.md").write_text("project", encoding="utf-8")
    config = make_config(tmp_path, two_experts=False)
    dbm = Database(config.database_url)
    dbm.create_all()
    orchestrator = CouncilOrchestrator(config, adapter_factory=lambda cfg: FakeAdapter(cfg))
    db = dbm.SessionLocal()

    item = orchestrator.create_session(db, SessionCreate(title="t", topic="question", repo_path=str(repo)))
    item = await orchestrator.run_next_round(db, item.id)
    with pytest.raises(ValueError, match="requires a note"):
        await orchestrator.apply_human_action(db, item.id, HumanAction(action="redirect"))
