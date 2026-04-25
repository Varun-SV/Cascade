# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project aims to follow Semantic Versioning.

## [Unreleased]

## [1.1.0] - 2026-04-25

### Added
- **Full-screen Textual TUI** — running bare `cascade` now launches a polished interactive chat
  interface instead of showing help text.
- **7 built-in themes** selectable with `/theme <name>` inside the chat:
  `cascade` (default), `nord`, `dracula`, `catppuccin-mocha`, `gruvbox`, `tokyo-night`, `one-dark`.
  Selected theme is persisted across sessions in `~/.cascade/tui_state.json`.
- **Inline tool-call tree-view** — every agent tool call renders as a collapsible tree block
  (`▶ tool_name → └ input → └ output`) directly inside the chat bubble.
- **Live terminal output panels** — `run_command` tool calls stream stdout line-by-line into a
  scrollable `RichLog` panel during execution, then collapse to a single summary line on completion.
- **Collapsible thinking blocks** — agent reasoning is shown dimmed and collapsed by default;
  click to expand.
- **Inline approval prompts** — tool approval requests render as Allow / Deny buttons inside the
  chat stream instead of interrupting the terminal.
- **Slash commands** in chat: `/theme`, `/clear`, `/help`, `/search`, `/run`, `/read`,
  `/budget`, `/config`, `/exit`.
- **`cascade init` interactive wizard** — 7-screen Textual wizard covering provider selection
  (Anthropic, OpenAI, OpenAI-compatible, Azure, Google, Ollama), per-provider credentials,
  planner selection, budget, approval mode, and a live YAML preview before saving.
- **`cascade doctor` animated TUI** — each health check animates with a spinner, resolves to
  ✓ / ✗, and failing checks expose a **Fix** button that opens an inline modal to apply the fix
  and immediately re-run the check.
- **Azure OpenAI multi-endpoint support** — new `azure_endpoints` config block supports multiple
  named Azure resources, each with its own `base_url`, `api_key`, `api_version`, and
  `deployment_name`. Models reference an endpoint by name via `azure_endpoint:`. API keys can be
  set via `CASCADE_AZURE_<NAME>_API_KEY` environment variables.
- **`AzureProvider`** — new provider class (extends `OpenAIProvider`) using
  `openai.AsyncAzureOpenAI`, with full `generate()`, `stream()`, and cost estimation support.
- **`textual>=0.70.0`** promoted from optional dependency to a required one.

### Changed
- `cascade chat` command **removed** — bare `cascade` now goes directly to the TUI chat.
- `cascade init` and `cascade doctor` automatically launch their TUI variants when running in an
  interactive terminal; pass `--output json` to use the original non-interactive output.
- `config.example.yaml` updated with Azure endpoint configuration examples.

### Fixed
- Non-TTY detection for bare `cascade` invocations — pipes and scripts get a clear error
  message directing them to `cascade run <task>` instead of attempting to launch the TUI.

## [1.0.0] - 2026-03-23

### Added
- Initial public release of Cascade as a multi-tier AI agent orchestration system.
