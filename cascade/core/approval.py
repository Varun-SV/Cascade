"""Approval primitives for guarded tool execution."""

from __future__ import annotations

import inspect
from enum import Enum
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field


class ApprovalMode(str, Enum):
    """Supported approval strategies."""

    GUARDED = "guarded"
    POWER_USER = "power_user"
    STRICT = "strict"


class ApprovalRequest(BaseModel):
    """A request for user approval before a risky tool action."""

    tool_name: str
    reason: str
    summary: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    command_prefix: list[str] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    """Normalized approval callback result."""

    approved: bool
    reason: str = ""


ApprovalHandler = Callable[
    [ApprovalRequest],
    Awaitable[ApprovalDecision | bool | tuple[bool, str]] | ApprovalDecision | bool | tuple[bool, str],
]


def command_prefix_matches(
    command_prefix: list[str], allowed_prefixes: list[list[str]] | None
) -> bool:
    """Return True when a parsed command prefix is allowlisted."""
    if not command_prefix or not allowed_prefixes:
        return False

    for allowed in allowed_prefixes:
        if not allowed:
            continue
        if command_prefix[: len(allowed)] == allowed:
            return True
    return False


async def resolve_approval(
    request: ApprovalRequest,
    handler: ApprovalHandler | None,
) -> ApprovalDecision:
    """Normalize approval callback output into a consistent decision model."""
    if handler is None:
        return ApprovalDecision(approved=False, reason="No approval handler is configured.")

    result = handler(request)
    if inspect.isawaitable(result):
        result = await result

    if isinstance(result, ApprovalDecision):
        return result
    if isinstance(result, tuple):
        approved, reason = result
        return ApprovalDecision(approved=bool(approved), reason=str(reason))
    return ApprovalDecision(approved=bool(result))
