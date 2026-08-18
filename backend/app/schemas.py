from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    topic: str = Field(min_length=1)
    repo_path: str = Field(min_length=1)


class HumanAction(BaseModel):
    action: Literal["continue", "redirect", "investigate", "stop"]
    note: str | None = None


class ExpertResponse(BaseModel):
    model_id: str
    display_name: str
    content: str
    error: str | None = None


class RoundOut(BaseModel):
    id: str
    number: int
    kind: str
    opening_statement: str
    expert_responses: list[ExpertResponse]
    chairman_summary: str
    human_action: str | None
    human_note: str | None
    created_at: datetime
    completed_at: datetime


class SessionOut(BaseModel):
    id: str
    title: str
    topic: str
    repo_path: str
    repo_commit: str | None
    repo_context_truncated: bool
    status: str
    current_round: int
    created_at: datetime
    updated_at: datetime
    rounds: list[RoundOut] = Field(default_factory=list)
