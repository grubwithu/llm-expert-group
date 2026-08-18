from pathlib import Path

import pytest

from app.adapters import ModelAdapter
from app.config import ModelConfig, RepositoryConfig
from app.repository import RepositoryWorkspace
from app.secretary import SecretaryAgent


class ScriptedAdapter(ModelAdapter):
    def __init__(self, config, replies):
        super().__init__(config)
        self.replies = list(replies)

    async def generate(self, *, system: str, prompt: str) -> str:
        return self.replies.pop(0)


@pytest.mark.asyncio
async def test_secretary_validates_real_evidence(tmp_path: Path):
    (tmp_path / "README.md").write_text("alpha\nbeta\n", encoding="utf-8")
    cfg = ModelConfig(id="s", display_name="S", protocol="openai_responses", model="x", api_url="https://x", api_key="x")
    adapter = ScriptedAdapter(cfg, [
        '{"action":"read","path":"README.md","start_line":1,"end_line":2}',
        '{"action":"answer","answer":"README contains beta.","status":"VERIFIED","evidence":[{"path":"README.md","start_line":2,"end_line":2,"reason":"direct text"}],"limitations":[]}',
    ])
    agent = SecretaryAgent(adapter, RepositoryWorkspace(str(tmp_path), RepositoryConfig()))
    result = await agent.answer("Does README contain beta?", requester_role="expert", requester_id="x", phase="expert", sequence=1)
    assert result.status == "VERIFIED"
    assert result.evidence[0].path == "README.md"
    assert "2: beta" in (result.evidence[0].excerpt or "")


@pytest.mark.asyncio
async def test_secretary_downgrades_fake_verified_citation(tmp_path: Path):
    (tmp_path / "README.md").write_text("alpha\n", encoding="utf-8")
    cfg = ModelConfig(id="s", display_name="S", protocol="openai_responses", model="x", api_url="https://x", api_key="x")
    adapter = ScriptedAdapter(cfg, [
        '{"action":"answer","answer":"claim","status":"VERIFIED","evidence":[{"path":"missing.py","start_line":1,"end_line":2,"reason":"fake"}],"limitations":[]}',
    ])
    agent = SecretaryAgent(adapter, RepositoryWorkspace(str(tmp_path), RepositoryConfig()))
    result = await agent.answer("claim?", requester_role="chairman", requester_id="chair", phase="opening", sequence=1)
    assert result.status == "PARTIALLY_VERIFIED"
    assert result.evidence == []
    assert any("downgraded" in x for x in result.limitations)


def test_opening_baseline_includes_repository_inventory_and_document_content(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Project\nGoal: test rollback.\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('run')\n", encoding="utf-8")
    cfg = ModelConfig(id="s", display_name="S", protocol="openai_responses", model="x", api_url="https://x", api_key="x")
    agent = SecretaryAgent(ScriptedAdapter(cfg, []), RepositoryWorkspace(str(tmp_path), RepositoryConfig()))

    result = agent.opening_baseline(requester_role="chairman", requester_id="chair", sequence=1)

    assert result.status == "PARTIALLY_VERIFIED"
    assert "README.md" in result.answer
    assert "Goal: test rollback." in result.answer
    assert "src/main.py" in result.answer
    assert result.tool_trace[0].startswith("mandatory opening baseline")
