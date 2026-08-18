from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import AppConfig, ModelConfig, ReasoningConfig, load_config


def model(model_id: str) -> ModelConfig:
    return ModelConfig(id=model_id, display_name=model_id, protocol="openai_responses", model="x", api_url="https://x", api_key="x")


def test_secretary_must_reference_configured_model():
    with pytest.raises(ValidationError, match="secretary"):
        AppConfig(chairman="chair", secretary="missing", experts=["expert"], models=[model("chair"), model("expert")])


def test_reasoning_budget_requires_tokens():
    with pytest.raises(ValidationError, match="budget_tokens"):
        ReasoningConfig(mode="budget")


def test_reasoning_rejects_effort_and_budget_together():
    with pytest.raises(ValidationError, match="both effort and budget_tokens"):
        ReasoningConfig(effort="high", budget_tokens=4096)


def test_load_config_reads_nearby_dotenv_without_overriding_environment(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
chairman: chair
secretary: secretary
experts: [expert]
models:
  - id: chair
    display_name: Chair
    protocol: openai_responses
    model: example
    api_url: https://example.test/v1
    api_key_env: CHAIR_KEY
  - id: secretary
    display_name: Secretary
    protocol: openai_responses
    model: example
    api_url: https://example.test/v1
    api_key_env: SECRETARY_KEY
  - id: expert
    display_name: Expert
    protocol: openai_responses
    model: example
    api_url: https://example.test/v1
    api_key_env: EXPERT_KEY
""",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("CHAIR_KEY=from-dotenv\nSECRETARY_KEY='secretary key'\nEXPERT_KEY=expert\n", encoding="utf-8")
    monkeypatch.setenv("CHAIR_KEY", "from-process")
    monkeypatch.delenv("SECRETARY_KEY", raising=False)
    monkeypatch.delenv("EXPERT_KEY", raising=False)

    config = load_config(config_path)

    assert config.model_map["chair"].resolved_api_key() == "from-process"
    assert config.model_map["secretary"].resolved_api_key() == "secretary key"
    assert config.model_map["expert"].resolved_api_key() == "expert"
