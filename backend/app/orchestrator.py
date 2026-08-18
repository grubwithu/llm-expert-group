from __future__ import annotations

import asyncio
import json
import uuid
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .adapters import ModelAdapter, build_adapter
from .config import AppConfig, ModelConfig
from .db import CouncilRound, CouncilSession
from .prompts import (
    CHAIRMAN_SYSTEM, EXPERT_SYSTEM, expert_prompt, first_opening_prompt, next_opening_prompt, synthesis_prompt,
)
from .repository import snapshot_repository
from .schemas import ExpertResponse, HumanAction, RoundOut, SessionCreate, SessionOut

AdapterFactory = Callable[[ModelConfig], ModelAdapter]


class CouncilOrchestrator:
    def __init__(self, config: AppConfig, adapter_factory: AdapterFactory = build_adapter):
        self.config = config
        self.adapter_factory = adapter_factory

    def _load(self, db: Session, session_id: str) -> CouncilSession:
        statement = select(CouncilSession).execution_options(populate_existing=True).options(selectinload(CouncilSession.rounds)).where(CouncilSession.id == session_id)
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
        if item.current_round > 0:
            previous = item.rounds[-1]
            if previous.human_action is None:
                raise ValueError("human action is required before starting another round")
            if previous.human_action == "stop":
                raise ValueError("session is stopped")
            action = previous.human_action
            kind = "investigation" if action == "investigate" else "discussion"
        else:
            previous = None
            action = None
            kind = "discussion"

        item.status = "running"
        db.commit()

        chairman_cfg = self.config.model_map[self.config.chairman]
        chairman = self.adapter_factory(chairman_cfg)
        round_number = item.current_round + 1

        if previous is None:
            opening_request = first_opening_prompt(item.topic, item.repo_context, item.repo_commit, item.repo_context_truncated)
        else:
            opening_request = next_opening_prompt(
                topic=item.topic,
                repo_context=item.repo_context,
                previous_summary=previous.chairman_summary,
                action=action,  # type: ignore[arg-type]
                note=previous.human_note,
                round_number=round_number,
            )
        opening = await chairman.generate(system=CHAIRMAN_SYSTEM, prompt=opening_request)

        async def ask_expert(model_id: str) -> ExpertResponse:
            cfg = self.config.model_map[model_id]
            try:
                text = await self.adapter_factory(cfg).generate(
                    system=EXPERT_SYSTEM, prompt=expert_prompt(opening, round_number, kind)
                )
                return ExpertResponse(model_id=model_id, display_name=cfg.display_name, content=text)
            except Exception as exc:  # isolate one provider failure from the whole council
                return ExpertResponse(model_id=model_id, display_name=cfg.display_name, content="", error=str(exc))

        expert_results = await asyncio.gather(*(ask_expert(model_id) for model_id in self.config.experts))
        successful = [(result.display_name, result.content) for result in expert_results if not result.error and result.content]
        if not successful:
            item.status = "error"
            db.commit()
            raise RuntimeError("all expert model calls failed")

        summary = await chairman.generate(
            system=CHAIRMAN_SYSTEM,
            prompt=synthesis_prompt(
                topic=item.topic,
                repo_context=item.repo_context,
                opening=opening,
                responses=successful,
                round_number=round_number,
            ),
        )

        round_row = CouncilRound(
            id=str(uuid.uuid4()),
            session_id=item.id,
            number=round_number,
            kind=kind,
            opening_statement=opening,
            expert_responses_json=json.dumps([r.model_dump() for r in expert_results], ensure_ascii=False),
            chairman_summary=summary,
        )
        db.add(round_row)
        item.current_round = round_number
        item.status = "awaiting_human"
        db.commit()
        return self._load(db, session_id)

    def apply_human_action(self, db: Session, session_id: str, action: HumanAction) -> CouncilSession:
        item = self._load(db, session_id)
        if item.status != "awaiting_human" or not item.rounds:
            raise ValueError("session is not waiting for a human action")
        latest = item.rounds[-1]
        if latest.human_action is not None:
            raise ValueError("human action has already been recorded for this round")
        if action.action in {"redirect", "investigate"} and not (action.note and action.note.strip()):
            raise ValueError(f"{action.action} requires a note describing the new focus")
        latest.human_action = action.action
        latest.human_note = action.note
        item.status = "stopped" if action.action == "stop" else "ready"
        db.commit()
        return self._load(db, session_id)


def to_session_out(item: CouncilSession) -> SessionOut:
    rounds = []
    for row in item.rounds:
        rounds.append(RoundOut(
            id=row.id,
            number=row.number,
            kind=row.kind,
            opening_statement=row.opening_statement,
            expert_responses=[ExpertResponse.model_validate(x) for x in json.loads(row.expert_responses_json)],
            chairman_summary=row.chairman_summary,
            human_action=row.human_action,
            human_note=row.human_note,
            created_at=row.created_at,
            completed_at=row.completed_at,
        ))
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
