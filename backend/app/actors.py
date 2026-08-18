from __future__ import annotations

from dataclasses import dataclass
import re
from collections.abc import Awaitable, Callable
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


DeltaHandler = Callable[[str], Awaitable[None]]
StatusHandler = Callable[[str, dict[str, str]], Awaitable[None]]


class _JsonContentExtractor:
    """Incrementally extracts the ``content`` string from the actor protocol."""

    _content_start = re.compile(r'"content"\s*:\s*"')

    def __init__(self) -> None:
        self.raw = ""
        self.index = 0
        self.started = False
        self.done = False
        self.escaped = False
        self.unicode_digits: str | None = None

    def feed(self, fragment: str) -> str:
        self.raw += fragment
        if not self.started:
            match = self._content_start.search(self.raw)
            if match is None:
                return ""
            self.started = True
            self.index = match.end()

        output: list[str] = []
        while self.index < len(self.raw) and not self.done:
            char = self.raw[self.index]
            self.index += 1
            if self.unicode_digits is not None:
                self.unicode_digits += char
                if len(self.unicode_digits) == 4:
                    try:
                        output.append(chr(int(self.unicode_digits, 16)))
                    except ValueError:
                        output.append("\\u" + self.unicode_digits)
                    self.unicode_digits = None
                continue
            if self.escaped:
                self.escaped = False
                if char == "u":
                    self.unicode_digits = ""
                else:
                    output.append({"n": "\n", "r": "\r", "t": "\t"}.get(char, char))
                continue
            if char == "\\":
                self.escaped = True
            elif char == '"':
                self.done = True
            else:
                output.append(char)
        return "".join(output)


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

    async def _stream_once(self, prompt: str, on_delta: DeltaHandler) -> str:
        extractor = _JsonContentExtractor()
        parts: list[str] = []
        async for fragment in self.adapter.stream(system=self.system_prompt, prompt=prompt):
            parts.append(fragment)
            content_delta = extractor.feed(fragment)
            if content_delta:
                await on_delta(content_delta)
        raw = "".join(parts).strip()
        # A non-protocol-compatible model may not emit JSON. Preserve the
        # existing compatibility behavior and still show its final output.
        # A valid ask_secretary action is internal protocol, never prose.
        parsed = extract_json_object(raw)
        if raw and not extractor.started and not (parsed and parsed.get("action") == "ask_secretary"):
            await on_delta(raw)
        return raw

    async def _stream_forced_final(self, transcript: str, on_delta: DeltaHandler) -> tuple[str, dict | None]:
        """Give an empty or malformed protocol reply one bounded recovery attempt."""
        prompt = transcript + (
            "\n\nSYSTEM CONTROL: Your previous reply did not contain a usable final answer. "
            "Do not ask the Secretary again. Return exactly one non-empty JSON object "
            'of the form {"action":"final","content":"..."}.'
        )
        raw = await self._stream_once(prompt, on_delta)
        return raw, extract_json_object(raw)

    async def run_stream(
        self,
        task: str,
        on_delta: DeltaHandler,
        on_status: StatusHandler | None = None,
        secretary_sequence_offset: int = 0,
    ) -> ActorResult:
        """Run the actor protocol while exposing only final-answer text tokens."""
        transcript = actor_protocol(task, max_queries=self.max_secretary_queries)
        queries: list[SecretaryInteraction] = []
        warnings: list[str] = []
        query_count = 0

        while True:
            raw = await self._stream_once(transcript, on_delta)
            parsed = extract_json_object(raw)
            if not raw:
                warnings.append("Actor stream ended without text; requested one non-streaming-compatible final reply.")
                raw, parsed = await self._stream_forced_final(transcript, on_delta)
            if parsed is None:
                warnings.append("Actor returned non-JSON output; accepted as final content for compatibility.")
                return ActorResult(content=raw, secretary_queries=queries, protocol_warnings=warnings)

            action = parsed.get("action")
            if action == "final":
                content = str(parsed.get("content") or "").strip()
                if not content:
                    warnings.append("Actor returned an empty final answer; requested one corrective final reply.")
                    raw, recovered = await self._stream_forced_final(transcript, on_delta)
                    if recovered and recovered.get("action") == "final":
                        content = str(recovered.get("content") or "").strip()
                    if not content:
                        warnings.append("Actor did not produce a non-empty final answer after the corrective retry.")
                return ActorResult(
                    content=content,
                    secretary_queries=queries,
                    protocol_warnings=warnings,
                )
            if action != "ask_secretary" or not str(parsed.get("question") or "").strip():
                warnings.append(f"Unknown actor action {action!r}; accepted raw output as final content.")
                return ActorResult(content=raw, secretary_queries=queries, protocol_warnings=warnings)
            if query_count >= self.max_secretary_queries:
                warnings.append("Secretary query budget exhausted; requesting a final response without more tools.")
                force_prompt = transcript + (
                    "\n\nSYSTEM CONTROL: No more Secretary queries are available. "
                    "You must now answer the task. Return exactly one JSON object "
                    'of the form {"action":"final","content":"..."}. Do not request another tool.'
                )
                raw = await self._stream_once(force_prompt, on_delta)
                parsed = extract_json_object(raw)
                content = str(parsed.get("content") or "").strip() if parsed and parsed.get("action") == "final" else raw
                if not (parsed and parsed.get("action") == "final"):
                    warnings.append("Actor did not follow the forced-final protocol; accepted its last output as final content.")
                return ActorResult(content=content, secretary_queries=queries, protocol_warnings=warnings)

            query_count += 1
            question = str(parsed["question"]).strip()
            sequence = secretary_sequence_offset + query_count
            if on_status:
                await on_status("secretary.started", {"question": question, "sequence": str(sequence)})
            interaction = await self.secretary.answer(
                question,
                requester_role=self.requester_role,
                requester_id=self.requester_id,
                phase=self.phase,
                sequence=sequence,
            )
            queries.append(interaction)
            if on_status:
                await on_status("secretary.completed", {"sequence": str(sequence), "status": interaction.status})
            transcript += (
                f"\n\nSECRETARY ANSWER #{query_count}\n"
                f"Question: {interaction.question}\n"
                f"Status: {interaction.status}\n"
                f"Repository commit observed: {interaction.repo_commit or 'not available'}\n"
                f"Answer: {interaction.answer}\n"
            )
            if interaction.evidence:
                citations = "; ".join(f"{e.path}:{e.start_line}-{e.end_line}" for e in interaction.evidence)
                transcript += f"Evidence: {citations}\n"
            if interaction.limitations:
                transcript += "Limitations: " + "; ".join(interaction.limitations) + "\n"
            transcript += "\nContinue your analysis. Return one JSON action according to the protocol."

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
