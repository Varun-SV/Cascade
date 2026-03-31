# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project aims to follow Semantic Versioning.

## [Unreleased]

### Added
- Structured runtime models for execution context, working memory, retry reflections, delegation envelopes, and plan previews.
- An async event bus plus trace, journal, and rollback modules for execution observability.
- A provider router with fallback handling, prompt-budget checks, and local summarization hooks.
- A SQLite-backed budget ledger, benchmark runner, plugin registry, semantic code search, and diff preview tooling.
- New CLI commands: `explain`, `doctor`, `budget`, `trace`, `rollback`, `benchmark`, and `plugin ...`.
- Contributor and architecture documentation plus focused runtime, observability, provider, tooling, CLI, and harness tests.

### Changed
- Reworked the recursive agent loop into a reflection-retry-escalate flow with working memory and structured delegation.
- Expanded configuration with `runtime`, `observability`, `plugins`, `semantic_search`, and richer budget controls.
- Replaced the GitHub Pages workflow with CI for linting, type checking, unit tests, and harness coverage.

## [0.1.0]

### Added
- Initial public release of Cascade as a multi-tier AI agent orchestration system.
