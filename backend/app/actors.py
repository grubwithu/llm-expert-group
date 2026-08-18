from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from .adapters import ModelAdapter
from .prompts import actor_protocol
from .protocol import extract_json_object
from .schemas import SecretaryInteraction
from .secretary import SecretaryAgent


class ActorState(TypedDict, total=False):
    transcript: str
    query_count: int
    route: Literal["secretary", "done"]
    pending_question: str
    output: str
    secretary_queries: list[dict]
    protocol_warnings: list[str]


@dataclass(slots=True)
class ActorResult:
    content: str
    secretary_queries: list[SecretaryInteraction]
    protocol_warnings: list[str]


class CouncilActor:
    """Chairman/Expert actor loop with one capability: ask the Secretary."""

    def __init__(
        self,
        *,
        adapter: ModelAdapter,
        secretary: SecretaryAgent,
        system_prompt: str,
        requester_role: Literal["chairman", "expert"],
        requester_id: str | None,
        phase: Literal["opening", "expert", "synthesis"],
        max_secretary_queries: int,
    ):
        self.adapter = adapter
        self.secretary = secretary
        self.system_prompt = system_prompt
        self.requester_role = requester_role
        self.requester_id = requester_id
        self.phase = phase
        self.max_secretary_queries = max_secretary_queries
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(ActorState)
        builder.add_node("actor", self._actor_node)
        builder.add_node("secretary", self._secretary_node)
        builder.add_edge(START, "actor")
        builder.add_conditional_edges("actor", lambda state: state["route"], {"secretary": "secretary", "done": END})
        builder.add_edge("secretary", "actor")
        return builder.compile(checkpointer=False)

    async def _actor_node(self, state: ActorState) -> ActorState:
        raw = await self.adapter.generate(system=self.system_prompt, prompt=state["transcript"])
        parsed = extract_json_object(raw)
        warnings = list(state.get("protocol_warnings", []))
        if parsed is None:
            warnings.append("Actor returned non-JSON output; accepted as final content for compatibility.")
            return {"route": "done", "output": raw.strip(), "protocol_warnings": warnings}

        action = parsed.get("action")
        if action == "final":
            content = str(parsed.get("content") or "").strip()
            return {"route": "done", "output": content, "protocol_warnings": warnings}

        if action == "ask_secretary":
            question = str(parsed.get("question") or "").strip()
            if not question:
                warnings.append("Actor emitted ask_secretary without a question; requesting a final response instead.")
                return await self._force_final(state, warnings)
            if int(state.get("query_count", 0)) >= self.max_secretary_queries:
                warnings.append("Secretary query budget exhausted; requesting a final response without more tools.")
                return await self._force_final(state, warnings)
            return {"route": "secretary", "pending_question": question, "protocol_warnings": warnings}

        warnings.append(f"Unknown actor action {action!r}; accepted raw output as final content.")
        return {"route": "done", "output": raw.strip(), "protocol_warnings": warnings}


    async def _force_final(self, state: ActorState, warnings: list[str]) -> ActorState:
        prompt = state["transcript"] + (
            "\n\nSYSTEM CONTROL: No more Secretary queries are available. "
            "You must now answer the task. Return exactly one JSON object "
            'of the form {"action":"final","content":"..."}. Do not request another tool.'
        )
        raw = await self.adapter.generate(system=self.system_prompt, prompt=prompt)
        parsed = extract_json_object(raw)
        if parsed is not None and parsed.get("action") == "final":
            content = str(parsed.get("content") or "").strip()
            return {"route": "done", "output": content, "protocol_warnings": warnings}
        warnings.append("Actor did not follow the forced-final protocol; accepted its last output as final content.")
        return {"route": "done", "output": raw.strip(), "protocol_warnings": warnings}

    async def _secretary_node(self, state: ActorState) -> ActorState:
        sequence = int(state.get("query_count", 0)) + 1
        interaction = await self.secretary.answer(
            state["pending_question"],
            requester_role=self.requester_role,
            requester_id=self.requester_id,
            phase=self.phase,
            sequence=sequence,
        )
        existing = list(state.get("secretary_queries", []))
        existing.append(interaction.model_dump(mode="json"))
        transcript = state["transcript"] + (
            f"\n\nSECRETARY ANSWER #{sequence}\n"
            f"Question: {interaction.question}\n"
            f"Status: {interaction.status}\n"
            f"Repository commit observed: {interaction.repo_commit or 'not available'}\n"
            f"Answer: {interaction.answer}\n"
        )
        if interaction.evidence:
            citations = "; ".join(
                f"{e.path}:{e.start_line}-{e.end_line}" for e in interaction.evidence
            )
            transcript += f"Evidence: {citations}\n"
        if interaction.limitations:
            transcript += "Limitations: " + "; ".join(interaction.limitations) + "\n"
        transcript += "\nContinue your analysis. Return one JSON action according to the protocol."
        return {
            "transcript": transcript,
            "query_count": sequence,
            "secretary_queries": existing,
            "pending_question": "",
        }

    async def run(self, task: str) -> ActorResult:
        initial = actor_protocol(task, max_queries=self.max_secretary_queries)
        result = await self.graph.ainvoke(
            {
                "transcript": initial,
                "query_count": 0,
                "secretary_queries": [],
                "protocol_warnings": [],
            }
        )
        return ActorResult(
            content=result.get("output", "").strip(),
            secretary_queries=[SecretaryInteraction.model_validate(x) for x in result.get("secretary_queries", [])],
            protocol_warnings=[str(x) for x in result.get("protocol_warnings", [])],
        )
