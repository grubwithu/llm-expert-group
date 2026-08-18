from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from .actors import CouncilActor
from .adapters import ModelAdapter, build_adapter
from .config import AppConfig, ModelConfig
from .prompts import (
    CHAIRMAN_SYSTEM,
    EXPERT_SYSTEM,
    expert_prompt,
    first_opening_prompt,
    next_opening_prompt,
    synthesis_prompt,
)
from .repository import RepositoryWorkspace
from .schemas import ExpertResponse, HumanAction
from .secretary import SecretaryAgent


class CouncilGraphState(TypedDict, total=False):
    session_id: str
    round_number: int
    topic: str
    repo_path: str
    repo_commit: str | None
    repo_context_truncated: bool
    kind: str
    previous_summary: str
    previous_action: str | None
    previous_note: str | None
    opening_statement: str
    model_id: str
    expert_results: Annotated[list[dict[str, Any]], operator.add]
    secretary_interactions: Annotated[list[dict[str, Any]], operator.add]
    chairman_summary: str
    human_action: str | None
    human_note: str | None


class CouncilGraphRuntime:
    """Pure LangGraph orchestration. Domain persistence stays in SQLAlchemy."""

    def __init__(self, config: AppConfig, adapter_factory=build_adapter):
        self.config = config
        self.adapter_factory = adapter_factory

    def _secretary(self, repo_path: str) -> SecretaryAgent:
        cfg = self.config.model_map[self.config.secretary]
        return SecretaryAgent(
            self.adapter_factory(cfg),
            RepositoryWorkspace(repo_path, self.config.repository),
            max_steps=self.config.secretary_max_tool_steps,
        )

    def _actor(
        self,
        *,
        model: ModelConfig,
        repo_path: str,
        system_prompt: str,
        requester_role: str,
        requester_id: str | None,
        phase: str,
    ) -> CouncilActor:
        return CouncilActor(
            adapter=self.adapter_factory(model),
            secretary=self._secretary(repo_path),
            system_prompt=system_prompt,
            requester_role=requester_role,  # type: ignore[arg-type]
            requester_id=requester_id,
            phase=phase,  # type: ignore[arg-type]
            max_secretary_queries=self.config.actor_max_secretary_queries,
        )

    async def chairman_open(self, state: CouncilGraphState) -> CouncilGraphState:
        round_number = state["round_number"]
        previous_action = state.get("previous_action")
        if round_number == 1 or not previous_action:
            task = first_opening_prompt(
                state["topic"],
                state.get("repo_commit"),
                bool(state.get("repo_context_truncated")),
            )
        else:
            task = next_opening_prompt(
                topic=state["topic"],
                previous_summary=state.get("previous_summary", ""),
                action=previous_action,
                note=state.get("previous_note"),
                round_number=round_number,
            )
        cfg = self.config.model_map[self.config.chairman]
        actor = self._actor(
            model=cfg,
            repo_path=state["repo_path"],
            system_prompt=CHAIRMAN_SYSTEM,
            requester_role="chairman",
            requester_id=self.config.chairman,
            phase="opening",
        )
        result = await actor.run(task)
        if not result.content:
            raise RuntimeError("chairman produced an empty opening statement")
        return {
            "opening_statement": result.content,
            "secretary_interactions": [x.model_dump(mode="json") for x in result.secretary_queries],
        }

    def fan_out_experts(self, state: CouncilGraphState):
        shared = {
            "session_id": state["session_id"],
            "round_number": state["round_number"],
            "kind": state["kind"],
            "repo_path": state["repo_path"],
            "opening_statement": state["opening_statement"],
        }
        return [Send("expert_worker", {**shared, "model_id": model_id}) for model_id in self.config.experts]

    async def expert_worker(self, state: CouncilGraphState) -> CouncilGraphState:
        model_id = state["model_id"]
        cfg = self.config.model_map[model_id]
        try:
            actor = self._actor(
                model=cfg,
                repo_path=state["repo_path"],
                system_prompt=EXPERT_SYSTEM,
                requester_role="expert",
                requester_id=model_id,
                phase="expert",
            )
            result = await actor.run(
                expert_prompt(state["opening_statement"], state["round_number"], state["kind"])
            )
            response = ExpertResponse(
                model_id=model_id,
                display_name=cfg.display_name,
                content=result.content,
                secretary_queries=result.secretary_queries,
                protocol_warnings=result.protocol_warnings,
            )
            interactions = [x.model_dump(mode="json") for x in result.secretary_queries]
        except Exception as exc:  # provider/tool failure isolation per expert branch
            response = ExpertResponse(
                model_id=model_id,
                display_name=cfg.display_name,
                content="",
                error=str(exc),
            )
            interactions = []
        return {
            "expert_results": [response.model_dump(mode="json")],
            "secretary_interactions": interactions,
        }

    async def chairman_synthesize(self, state: CouncilGraphState) -> CouncilGraphState:
        results = [ExpertResponse.model_validate(x) for x in state.get("expert_results", [])]
        order = {model_id: i for i, model_id in enumerate(self.config.experts)}
        results.sort(key=lambda x: order.get(x.model_id, len(order)))
        successful = [(item.display_name, item.content) for item in results if item.content and not item.error]
        if not successful:
            raise RuntimeError("all expert model calls failed")

        cfg = self.config.model_map[self.config.chairman]
        actor = self._actor(
            model=cfg,
            repo_path=state["repo_path"],
            system_prompt=CHAIRMAN_SYSTEM,
            requester_role="chairman",
            requester_id=self.config.chairman,
            phase="synthesis",
        )
        result = await actor.run(
            synthesis_prompt(
                topic=state["topic"],
                opening=state["opening_statement"],
                responses=successful,
                round_number=state["round_number"],
            )
        )
        if not result.content:
            raise RuntimeError("chairman produced an empty synthesis")
        return {
            "expert_results": [],  # reducer receives this as a no-op; existing results stay available
            "chairman_summary": result.content,
            "secretary_interactions": [x.model_dump(mode="json") for x in result.secretary_queries],
        }

    def human_gate(self, state: CouncilGraphState) -> CouncilGraphState:
        decision = interrupt(
            {
                "type": "human_gate",
                "session_id": state["session_id"],
                "round_number": state["round_number"],
                "question": "Choose continue, redirect, investigate, or stop.",
                "chairman_summary": state["chairman_summary"],
            }
        )
        action = HumanAction.model_validate(decision)
        return {"human_action": action.action, "human_note": action.note}

    def build(self, checkpointer):
        builder = StateGraph(CouncilGraphState)
        builder.add_node("chairman_open", self.chairman_open)
        builder.add_node("expert_worker", self.expert_worker)
        builder.add_node("chairman_synthesize", self.chairman_synthesize)
        builder.add_node("human_gate", self.human_gate)
        builder.add_edge(START, "chairman_open")
        builder.add_conditional_edges("chairman_open", self.fan_out_experts, ["expert_worker"])
        builder.add_edge("expert_worker", "chairman_synthesize")
        builder.add_edge("chairman_synthesize", "human_gate")
        builder.add_edge("human_gate", END)
        return builder.compile(checkpointer=checkpointer)
