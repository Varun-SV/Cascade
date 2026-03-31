"""Provider router with fallback, prompt-budget management, and streaming helpers."""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable

from cascade.config import CascadeConfig, ModelConfig
from cascade.core.events import EventBus
from cascade.core.runtime import EventLevel, ExecutionContext, ExecutionEvent
from cascade.providers.base import BaseProvider, Message, Response, Role, StreamChunk, ToolSchema


def estimate_message_tokens(messages: list[Message]) -> int:
    """Cheap token estimator used for prompt-budget checks."""
    total_chars = 0
    for message in messages:
        total_chars += len(message.content or "")
        for tool_call in message.tool_calls:
            total_chars += len(tool_call.name) + len(str(tool_call.arguments))
        if message.tool_result:
            total_chars += len(message.tool_result.content)
    return max(total_chars // 4, len(messages) * 16)


def is_transient_provider_error(error: Exception) -> bool:
    """Best-effort classification for retryable provider failures."""
    text = str(error).lower()
    transient_markers = [
        "rate limit",
        "too many requests",
        "timeout",
        "temporarily unavailable",
        "service unavailable",
        "529",
        "overloaded",
        "connection reset",
    ]
    return any(marker in text for marker in transient_markers)


class ProviderRouter(BaseProvider):
    """Route a request through a primary provider with fallback and summarization."""

    def __init__(
        self,
        *,
        model_id: str,
        config: CascadeConfig,
        provider_factory: Callable[[str], BaseProvider],
        event_bus: EventBus | None = None,
        execution_context: ExecutionContext | None = None,
    ):
        model_config = config.get_model(model_id)
        super().__init__(model=model_config.model)
        self.model_id = model_id
        self.config = config
        self._provider_factory = provider_factory
        self._event_bus = event_bus
        self._execution_context = execution_context
        self._last_provider: BaseProvider | None = None

    def _candidate_model_ids(self) -> list[str]:
        model_config = self.config.get_model(self.model_id)
        candidates = [self.model_id]
        for fallback in model_config.fallback_models:
            if fallback not in candidates:
                candidates.append(fallback)
        return candidates

    def _context_window(self, model_config: ModelConfig) -> int:
        if model_config.context_window:
            return model_config.context_window
        if model_config.provider == "ollama":
            return 32768
        return 131072

    async def _emit(self, message: str, *, event_type: str, payload: dict[str, Any] | None = None) -> None:
        if not self._event_bus or not self._execution_context:
            return
        await self._event_bus.emit(
            ExecutionEvent(
                event_type=event_type,
                task_id=self._execution_context.task_id,
                session_id=self._execution_context.session_id,
                agent_id=self._execution_context.current_agent_id,
                model_id=self._execution_context.current_model_id or self.model_id,
                subtask_id=self._execution_context.current_subtask_id,
                level=EventLevel.INFO,
                message=message,
                payload=payload or {},
            )
        )

    async def _summarize_if_needed(
        self, messages: list[Message], max_tokens: int, target_model_id: str
    ) -> list[Message]:
        model_config = self.config.get_model(target_model_id)
        context_window = self._context_window(model_config)
        estimated = estimate_message_tokens(messages) + max_tokens
        if estimated <= context_window:
            return messages

        preserved = messages[-6:] if len(messages) > 6 else messages
        system_messages = [msg for msg in messages if msg.role.value == "system"]
        if system_messages:
            preserved = [system_messages[0]] + [msg for msg in preserved if msg.role.value != "system"]

        local_model_id = None
        for candidate in self.config.models:
            if candidate.provider == "ollama":
                local_model_id = candidate.id
                break

        if local_model_id and local_model_id != target_model_id:
            older_messages = messages[:-6] if len(messages) > 6 else messages[:-1]
            summary_prompt = (
                "Summarize the following prior conversation for continued agent execution. "
                "Preserve goal, constraints, completed work, blockers, and key tool results.\n\n"
                + "\n\n".join(f"{msg.role.value.upper()}: {msg.content}" for msg in older_messages if msg.content)
            )
            try:
                summarizer = self._provider_factory(local_model_id)
                summary_response = await summarizer.generate(
                    messages=[
                        Message(role=Role.SYSTEM, content="You compress execution context for another coding agent."),
                        Message(role=Role.USER, content=summary_prompt),
                    ],
                    tools=None,
                    temperature=0.0,
                    max_tokens=min(1024, self.config.get_model(local_model_id).max_tokens),
                )
                if summary_response.content:
                    summary_message = Message(
                        role=Role.SYSTEM,
                        content=f"Conversation summary:\n{summary_response.content}",
                    )
                    await self._emit(
                        "Summarized prompt history using the local model.",
                        event_type="provider.context.summarized",
                        payload={"target_model_id": target_model_id, "summary_model_id": local_model_id},
                    )
                    return [summary_message] + [
                        msg for msg in preserved if msg.content or msg.tool_calls or msg.tool_result
                    ]
            except Exception:
                pass

        await self._emit(
            "Prompt exceeded the model context window; older history was truncated deterministically.",
            event_type="provider.context.truncated",
            payload={"target_model_id": target_model_id, "estimated_tokens": estimated},
        )
        return preserved

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Response:
        """Generate a completion with fallback-aware routing."""
        last_error: Exception | None = None
        for candidate_model_id in self._candidate_model_ids():
            provider = self._provider_factory(candidate_model_id)
            self._last_provider = provider
            prepared = await self._summarize_if_needed(messages, max_tokens, candidate_model_id)
            try:
                response = await provider.generate(
                    messages=prepared,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                await self._emit(
                    f"Provider route succeeded via {candidate_model_id}.",
                    event_type="provider.route.success",
                    payload={"model_id": candidate_model_id, "provider": self.config.get_model(candidate_model_id).provider},
                )
                return response
            except Exception as error:  # pragma: no cover - exact SDK failures vary
                last_error = error
                await self._emit(
                    f"Provider route failed via {candidate_model_id}: {error}",
                    event_type="provider.route.failure",
                    payload={"model_id": candidate_model_id, "error": str(error)},
                )
                if candidate_model_id == self._candidate_model_ids()[-1] or not is_transient_provider_error(error):
                    break
                await self._emit(
                    f"Falling back from {candidate_model_id} to the next configured provider.",
                    event_type="provider.route.fallback",
                    payload={"from_model_id": candidate_model_id},
                )

        if last_error is None:
            raise RuntimeError("ProviderRouter could not find a provider candidate.")
        raise last_error

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion from the routed provider."""
        last_error: Exception | None = None
        for candidate_model_id in self._candidate_model_ids():
            provider = self._provider_factory(candidate_model_id)
            self._last_provider = provider
            prepared = await self._summarize_if_needed(messages, max_tokens, candidate_model_id)
            try:
                async for chunk in provider.stream(
                    messages=prepared,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    yield chunk
                return
            except Exception as error:  # pragma: no cover - exact SDK failures vary
                last_error = error
                if candidate_model_id == self._candidate_model_ids()[-1] or not is_transient_provider_error(error):
                    break
        if last_error is None:
            raise RuntimeError("ProviderRouter could not find a provider candidate.")
        raise last_error

    def get_cost(self, usage: Any) -> float:
        """Delegate cost calculation to the last successful provider."""
        if self._last_provider is None:
            return 0.0
        return self._last_provider.get_cost(usage)

    def supports_tools(self) -> bool:
        """All routed providers are expected to expose the base interface."""
        return True

    async def list_models(self) -> list[str]:
        """List models through the primary provider."""
        provider = self._provider_factory(self.model_id)
        return await provider.list_models()
