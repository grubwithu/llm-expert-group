import pytest
from pydantic import ValidationError

from app.config import AppConfig, ModelConfig


def model(model_id: str) -> ModelConfig:
    return ModelConfig(id=model_id, display_name=model_id, protocol="openai_responses", model="x", api_url="https://x", api_key="x")


def test_secretary_must_reference_configured_model():
    with pytest.raises(ValidationError, match="secretary"):
        AppConfig(chairman="chair", secretary="missing", experts=["expert"], models=[model("chair"), model("expert")])
