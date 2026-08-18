from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

Protocol = Literal["openai_responses", "anthropic_messages", "openai_chat_completions"]


class ModelConfig(BaseModel):
    id: str
    display_name: str
    protocol: Protocol
    model: str
    api_url: str
    api_key: str | None = None
    api_key_env: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = 120.0

    @model_validator(mode="after")
    def validate_key_source(self) -> "ModelConfig":
        if not self.api_key and not self.api_key_env:
            raise ValueError(f"model {self.id!r} must define api_key or api_key_env")
        return self

    def resolved_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        assert self.api_key_env
        value = os.getenv(self.api_key_env)
        if not value:
            raise RuntimeError(f"environment variable {self.api_key_env!r} is not set for model {self.id!r}")
        return value

    def public_dict(self) -> dict[str, Any]:
        data = self.model_dump(exclude={"api_key"})
        data["api_key_configured"] = bool(self.api_key or (self.api_key_env and os.getenv(self.api_key_env)))
        return data


class RepositoryConfig(BaseModel):
    max_files: int = 180
    max_file_bytes: int = 160_000
    max_context_chars: int = 180_000
    include_suffixes: list[str] = Field(default_factory=lambda: [
        ".md", ".rst", ".txt", ".py", ".go", ".rs", ".c", ".h", ".cc", ".cpp", ".hpp",
        ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml", ".toml", ".sh", ".sql"
    ])
    exclude_dirs: list[str] = Field(default_factory=lambda: [
        ".git", ".idea", ".vscode", "node_modules", "dist", "build", ".venv", "venv", "__pycache__",
        ".pytest_cache", ".mypy_cache", ".next", "coverage", "vendor"
    ])


class AppConfig(BaseModel):
    chairman: str
    secretary: str
    experts: list[str]
    actor_max_secretary_queries: int = 4
    secretary_max_tool_steps: int = 8
    models: list[ModelConfig]
    database_url: str = "sqlite:///./data/council.db"
    langgraph_checkpoint_path: str = "./data/langgraph-checkpoints.sqlite"
    langgraph_max_concurrency: int = 8
    repository: RepositoryConfig = Field(default_factory=RepositoryConfig)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @model_validator(mode="after")
    def validate_model_refs(self) -> "AppConfig":
        ids = {model.id for model in self.models}
        if self.chairman not in ids:
            raise ValueError(f"chairman {self.chairman!r} is not defined in models")
        if self.secretary not in ids:
            raise ValueError(f"secretary {self.secretary!r} is not defined in models")
        missing = [item for item in self.experts if item not in ids]
        if missing:
            raise ValueError(f"unknown expert model ids: {missing}")
        if self.chairman in self.experts:
            raise ValueError("chairman must not also be listed as an expert")
        if not self.experts:
            raise ValueError("at least one expert is required")
        if self.actor_max_secretary_queries < 0:
            raise ValueError("actor_max_secretary_queries must be >= 0")
        if self.secretary_max_tool_steps < 1:
            raise ValueError("secretary_max_tool_steps must be >= 1")
        if self.langgraph_max_concurrency < 1:
            raise ValueError("langgraph_max_concurrency must be >= 1")
        return self

    @property
    def model_map(self) -> dict[str, ModelConfig]:
        return {model.id: model for model in self.models}


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path or os.getenv("LLM_EXPERT_GROUP_CONFIG", "config.yaml"))
    if not config_path.exists():
        raise FileNotFoundError(
            f"configuration file {config_path} not found; copy config.example.yaml to config.yaml or set LLM_EXPERT_GROUP_CONFIG"
        )
    with config_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return AppConfig.model_validate(data)
