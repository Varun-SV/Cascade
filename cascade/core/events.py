"""Async event bus for execution, tracing, and live status updates."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from cascade.core.runtime import ExecutionEvent

EventSubscriber = Callable[[ExecutionEvent], Any | Awaitable[Any]]


class EventBus:
    """Simple async fan-out event bus with in-memory history."""

    def __init__(self) -> None:
        self._subscribers: list[EventSubscriber] = []
        self._history: list[ExecutionEvent] = []

    @property
    def history(self) -> list[ExecutionEvent]:
        """Return emitted event history for the current process."""
        return list(self._history)

    def subscribe(self, subscriber: EventSubscriber) -> Callable[[], None]:
        """Register a subscriber and return an unsubscribe callback."""
        self._subscribers.append(subscriber)

        def _unsubscribe() -> None:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

        return _unsubscribe

    async def emit(self, event: ExecutionEvent) -> None:
        """Emit an event to all subscribers."""
        self._history.append(event)
        for subscriber in list(self._subscribers):
            result = subscriber(event)
            if inspect.isawaitable(result):
                await result

    async def emit_many(self, events: list[ExecutionEvent]) -> None:
        """Emit multiple events in order."""
        for event in events:
            await self.emit(event)
