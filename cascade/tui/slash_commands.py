"""Slash command registry and dispatcher for the chat TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Coroutine, Any

if TYPE_CHECKING:
    from cascade.tui.screens.chat import ChatScreen

Handler = Callable[["ChatScreen", str], Coroutine[Any, Any, None]]

_REGISTRY: dict[str, tuple[str, Handler]] = {}


def command(name: str, help_text: str) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        _REGISTRY[name] = (help_text, fn)
        return fn
    return decorator


@command("theme", "Change the color theme. Usage: /theme <name>")
async def _theme(screen: "ChatScreen", args: str) -> None:
    from cascade.tui.themes import THEMES, apply_theme

    name = args.strip()
    if not name:
        names = ", ".join(THEMES.keys())
        screen.message_list.add_system_bubble(
            f"Available themes: {names}\nUsage: /theme <name>"
        )
        return
    if apply_theme(screen.app, name):
        screen.message_list.add_system_bubble(f"Theme changed to '{name}'.")
    else:
        names = ", ".join(THEMES.keys())
        screen.message_list.add_system_bubble(
            f"Unknown theme '{name}'. Available: {names}"
        )


@command("clear", "Clear the chat history.")
async def _clear(screen: "ChatScreen", args: str) -> None:
    screen.message_list.clear_messages()
    screen.message_list.add_system_bubble("Chat cleared.")


@command("help", "Show available slash commands.")
async def _help(screen: "ChatScreen", args: str) -> None:
    lines = ["**Available commands:**\n"]
    for name, (help_text, _) in sorted(_REGISTRY.items()):
        lines.append(f"  /{name}  —  {help_text}")
    screen.message_list.add_system_bubble("\n".join(lines))


@command("exit", "Exit Cascade.")
async def _exit(screen: "ChatScreen", args: str) -> None:
    screen.app.exit()


@command("quit", "Exit Cascade.")
async def _quit(screen: "ChatScreen", args: str) -> None:
    screen.app.exit()


@command("search", "Web search. Usage: /search <query>")
async def _search(screen: "ChatScreen", args: str) -> None:
    if not args.strip():
        screen.message_list.add_system_bubble("Usage: /search <query>")
        return
    await screen.start_agent(f"Search the web for: {args.strip()}")


@command("run", "Run a shell command. Usage: /run <command>")
async def _run(screen: "ChatScreen", args: str) -> None:
    if not args.strip():
        screen.message_list.add_system_bubble("Usage: /run <command>")
        return
    await screen.start_agent(f"Run this shell command and show me the output: {args.strip()}")


@command("read", "Read a file. Usage: /read <path>")
async def _read(screen: "ChatScreen", args: str) -> None:
    if not args.strip():
        screen.message_list.add_system_bubble("Usage: /read <path>")
        return
    await screen.start_agent(f"Read and show me the contents of: {args.strip()}")


@command("budget", "Show current session cost.")
async def _budget(screen: "ChatScreen", args: str) -> None:
    try:
        summary = screen.cascade.budget_summary()
        total = summary.get("session_total", 0.0)
        screen.message_list.add_system_bubble(f"Session cost: ${total:.4f}")
    except Exception as exc:
        screen.message_list.add_system_bubble(f"Budget unavailable: {exc}")


@command("config", "Show active configuration.")
async def _config(screen: "ChatScreen", args: str) -> None:
    try:
        cfg = screen.cascade._config  # type: ignore[attr-defined]
        models = ", ".join(m.id for m in cfg.models)
        planner = cfg.default_planner
        screen.message_list.add_system_bubble(
            f"Planner: {planner}\nModels: {models}\nApproval: {cfg.approvals.mode.value}"
        )
    except Exception as exc:
        screen.message_list.add_system_bubble(f"Config unavailable: {exc}")


class SlashCommandHandler:
    """Dispatches slash commands to registered handlers."""

    def __init__(self, screen: "ChatScreen") -> None:
        self._screen = screen

    async def dispatch(self, raw: str) -> None:
        raw = raw.lstrip("/")
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        entry = _REGISTRY.get(cmd)
        if entry:
            _, handler = entry
            await handler(self._screen, args)
        else:
            names = ", ".join(f"/{n}" for n in sorted(_REGISTRY))
            self._screen.message_list.add_system_bubble(
                f"Unknown command '/{cmd}'.\nTry: {names}"
            )
