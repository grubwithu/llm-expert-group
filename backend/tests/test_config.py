import pytest
from pydantic import ValidationError

from app.config import AppConfig, ModelConfig, ReasoningConfig


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
