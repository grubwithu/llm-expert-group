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


SecretaryStatus = Literal["VERIFIED", "PARTIALLY_VERIFIED", "NOT_FOUND", "CONFLICTING_EVIDENCE", "UNSTRUCTURED"]


class SecretaryEvidence(BaseModel):
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    reason: str = ""
    excerpt: str | None = None


class SecretaryInteraction(BaseModel):
    id: str
    requester_role: Literal["chairman", "expert"]
    requester_id: str | None = None
    phase: Literal["opening", "expert", "synthesis"]
    sequence: int
    question: str
    answer: str
    status: SecretaryStatus
    evidence: list[SecretaryEvidence] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    tool_trace: list[str] = Field(default_factory=list)
    repo_commit: str | None = None


class ExpertResponse(BaseModel):
    model_id: str
    display_name: str
    content: str
    error: str | None = None
    secretary_queries: list[SecretaryInteraction] = Field(default_factory=list)
    protocol_warnings: list[str] = Field(default_factory=list)


class RoundOut(BaseModel):
    id: str
    number: int
    kind: str
    graph_thread_id: str | None = None
    opening_statement: str
    expert_responses: list[ExpertResponse]
    chairman_summary: str
    chairman_opening_secretary_queries: list[SecretaryInteraction] = Field(default_factory=list)
    chairman_synthesis_secretary_queries: list[SecretaryInteraction] = Field(default_factory=list)
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


class RoundRunOut(BaseModel):
    id: str
    session_id: str
    number: int
    kind: str
    status: str
    opening_statement: str
    expert_responses: list[ExpertResponse] = Field(default_factory=list)
    chairman_summary: str
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
