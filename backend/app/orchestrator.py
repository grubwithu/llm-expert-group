from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Callable

# LangGraph's SQLite saver recommends strict msgpack deserialization when the
# checkpoint database could be modified outside this process.
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .adapters import ModelAdapter, build_adapter
from .config import AppConfig, ModelConfig
from .db import CouncilRound, CouncilSession, SecretaryInteractionRow
from .graph_runtime import CouncilGraphRuntime
from .repository import snapshot_repository
from .schemas import (
    ExpertResponse,
    HumanAction,
    RoundOut,
    SecretaryEvidence,
    SecretaryInteraction,
    SessionCreate,
    SessionOut,
)

AdapterFactory = Callable[[ModelConfig], ModelAdapter]


class CouncilOrchestrator:
    def __init__(self, config: AppConfig, adapter_factory: AdapterFactory = build_adapter):
        self.config = config
        self.adapter_factory = adapter_factory
        self.runtime = CouncilGraphRuntime(config, adapter_factory=adapter_factory)
        checkpoint_path = Path(config.langgraph_checkpoint_path).expanduser()
        if str(checkpoint_path) != ":memory:":
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path = str(checkpoint_path)

    @staticmethod
    def _new_thread_id(session_id: str, round_number: int) -> str:
        # A fresh thread per execution attempt prevents stale partial reducer
        # state from a failed attempt contaminating a retry. The successful
        # thread id is persisted on CouncilRound for resume/replay/fork.
        return f"{session_id}:round:{round_number}:{uuid.uuid4()}"

    @staticmethod
    def _graph_config(thread_id: str, max_concurrency: int) -> dict:
        return {
            "configurable": {"thread_id": thread_id},
            "max_concurrency": max_concurrency,
        }

    def _load(self, db: Session, session_id: str) -> CouncilSession:
        rounds_load = selectinload(CouncilSession.rounds).selectinload(CouncilRound.secretary_interactions)
        statement = (
            select(CouncilSession)
            .execution_options(populate_existing=True)
            .options(rounds_load)
            .where(CouncilSession.id == session_id)
        )
        item = db.execute(statement).scalar_one_or_none()
        if item is None:
            raise KeyError(session_id)
        return item

    def create_session(self, db: Session, request: SessionCreate) -> CouncilSession:
        snapshot = snapshot_repository(request.repo_path, self.config.repository)
        item = CouncilSession(
            id=str(uuid.uuid4()),
            title=request.title,
            topic=request.topic,
            repo_path=snapshot.path,
            repo_commit=snapshot.commit,
            repo_context=snapshot.context,
            repo_context_truncated=snapshot.truncated,
            status="ready",
            current_round=0,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    async def run_next_round(self, db: Session, session_id: str) -> CouncilSession:
        item = self._load(db, session_id)
        if item.status == "stopped":
            raise ValueError("session is stopped")
        if item.status == "running":
            raise ValueError("session is already running")

        if item.current_round > 0:
            previous = item.rounds[-1]
            if previous.human_action is None:
                raise ValueError("human action is required before starting another round")
            if previous.human_action == "stop":
                raise ValueError("session is stopped")
            previous_action = previous.human_action
            kind = "investigation" if previous_action == "investigate" else "discussion"
        else:
            previous = None
            previous_action = None
            kind = "discussion"

        round_number = item.current_round + 1
        thread_id = self._new_thread_id(item.id, round_number)
        item.status = "running"
        db.commit()

        initial_state = {
            "session_id": item.id,
            "round_number": round_number,
            "topic": item.topic,
            "repo_path": item.repo_path,
            "repo_commit": item.repo_commit,
            "repo_context_truncated": item.repo_context_truncated,
            "kind": kind,
            "previous_summary": previous.chairman_summary if previous else "",
            "previous_action": previous_action,
            "previous_note": previous.human_note if previous else None,
            "expert_results": [],
            "secretary_interactions": [],
            "human_action": None,
            "human_note": None,
        }

        try:
            async with AsyncSqliteSaver.from_conn_string(self.checkpoint_path) as checkpointer:
                graph = self.runtime.build(checkpointer)
                result = await graph.ainvoke(
                    initial_state,
                    config=self._graph_config(thread_id, self.config.langgraph_max_concurrency),
                )
        except Exception as exc:
            item.status = "error"
            db.commit()
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(f"council graph execution failed: {exc}") from exc

        if not result.get("opening_statement") or not result.get("chairman_summary"):
            item.status = "error"
            db.commit()
            raise RuntimeError("LangGraph round stopped before producing opening and synthesis")
        if "__interrupt__" not in result:
            item.status = "error"
            db.commit()
            raise RuntimeError("LangGraph round did not pause at the Human Gate")

        expert_results = [ExpertResponse.model_validate(x) for x in result.get("expert_results", [])]
        expert_order = {model_id: i for i, model_id in enumerate(self.config.experts)}
        expert_results.sort(key=lambda x: expert_order.get(x.model_id, len(expert_order)))

        round_row = CouncilRound(
            id=str(uuid.uuid4()),
            session_id=item.id,
            number=round_number,
            kind=kind,
            graph_thread_id=thread_id,
            opening_statement=result["opening_statement"],
            expert_responses_json=json.dumps(
                [response.model_dump(mode="json") for response in expert_results], ensure_ascii=False
            ),
            chairman_summary=result["chairman_summary"],
        )
        db.add(round_row)
        for raw in result.get("secretary_interactions", []):
            interaction = SecretaryInteraction.model_validate(raw)
            round_row.secretary_interactions.append(_interaction_to_row(round_row.id, interaction))

        item.current_round = round_number
        item.status = "awaiting_human"
        db.commit()
        return self._load(db, session_id)

    async def apply_human_action(self, db: Session, session_id: str, action: HumanAction) -> CouncilSession:
        item = self._load(db, session_id)
        if item.status != "awaiting_human" or not item.rounds:
            raise ValueError("session is not waiting for a human action")
        latest = item.rounds[-1]
        if latest.human_action is not None:
            raise ValueError("human action has already been recorded for this round")
        if action.action in {"redirect", "investigate"} and not (action.note and action.note.strip()):
            raise ValueError(f"{action.action} requires a note describing the new focus")

        thread_id = latest.graph_thread_id
        if not thread_id:
            raise ValueError("round has no LangGraph thread id; it predates v0.2 and cannot be resumed")
        try:
            async with AsyncSqliteSaver.from_conn_string(self.checkpoint_path) as checkpointer:
                graph = self.runtime.build(checkpointer)
                resumed = await graph.ainvoke(
                    Command(resume=action.model_dump(mode="json")),
                    config=self._graph_config(thread_id, self.config.langgraph_max_concurrency),
                )
        except Exception as exc:
            raise RuntimeError(f"failed to resume LangGraph Human Gate: {exc}") from exc

        if resumed.get("human_action") != action.action:
            raise RuntimeError("LangGraph Human Gate did not accept the requested action")

        latest.human_action = action.action
        latest.human_note = action.note
        item.status = "stopped" if action.action == "stop" else "ready"
        db.commit()
        return self._load(db, session_id)


def _interaction_to_row(round_id: str, interaction: SecretaryInteraction) -> SecretaryInteractionRow:
    return SecretaryInteractionRow(
        id=interaction.id,
        round_id=round_id,
        requester_role=interaction.requester_role,
        requester_id=interaction.requester_id,
        phase=interaction.phase,
        sequence=interaction.sequence,
        question=interaction.question,
        answer=interaction.answer,
        status=interaction.status,
        evidence_json=json.dumps([x.model_dump(mode="json") for x in interaction.evidence], ensure_ascii=False),
        limitations_json=json.dumps(interaction.limitations, ensure_ascii=False),
        tool_trace_json=json.dumps(interaction.tool_trace, ensure_ascii=False),
        repo_commit=interaction.repo_commit,
    )


def _row_to_interaction(row: SecretaryInteractionRow) -> SecretaryInteraction:
    return SecretaryInteraction(
        id=row.id,
        requester_role=row.requester_role,  # type: ignore[arg-type]
        requester_id=row.requester_id,
        phase=row.phase,  # type: ignore[arg-type]
        sequence=row.sequence,
        question=row.question,
        answer=row.answer,
        status=row.status,  # type: ignore[arg-type]
        evidence=[SecretaryEvidence.model_validate(x) for x in json.loads(row.evidence_json or "[]")],
        limitations=[str(x) for x in json.loads(row.limitations_json or "[]")],
        tool_trace=[str(x) for x in json.loads(row.tool_trace_json or "[]")],
        repo_commit=row.repo_commit,
    )


def to_session_out(item: CouncilSession) -> SessionOut:
    rounds: list[RoundOut] = []
    for row in item.rounds:
        interactions = [_row_to_interaction(x) for x in row.secretary_interactions]
        opening_queries = [x for x in interactions if x.requester_role == "chairman" and x.phase == "opening"]
        synthesis_queries = [x for x in interactions if x.requester_role == "chairman" and x.phase == "synthesis"]
        expert_responses = [ExpertResponse.model_validate(x) for x in json.loads(row.expert_responses_json)]
        # The normalized table is canonical for provenance. Backfill from it if
        # the serialized response came from an older version or lacked queries.
        for response in expert_responses:
            if not response.secretary_queries:
                response.secretary_queries = [
                    x
                    for x in interactions
                    if x.requester_role == "expert" and x.requester_id == response.model_id and x.phase == "expert"
                ]
        rounds.append(
            RoundOut(
                id=row.id,
                number=row.number,
                kind=row.kind,
                graph_thread_id=row.graph_thread_id,
                opening_statement=row.opening_statement,
                expert_responses=expert_responses,
                chairman_summary=row.chairman_summary,
                chairman_opening_secretary_queries=opening_queries,
                chairman_synthesis_secretary_queries=synthesis_queries,
                human_action=row.human_action,
                human_note=row.human_note,
                created_at=row.created_at,
                completed_at=row.completed_at,
            )
        )
    return SessionOut(
        id=item.id,
        title=item.title,
        topic=item.topic,
        repo_path=item.repo_path,
        repo_commit=item.repo_commit,
        repo_context_truncated=item.repo_context_truncated,
        status=item.status,
        current_round=item.current_round,
        created_at=item.created_at,
        updated_at=item.updated_at,
        rounds=rounds,
    )
