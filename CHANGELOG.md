# Changelog

## 1.0.0 (2026-11)

First release on the GitHub Marketplace.

- Answers one question for a whole project: *is this code disproportionately large for what
  it does?* YES / PARTLY / NO with a 0–100 score, and every finding names the Clean Code
  heuristic it breaks.
- Python: dead code, pass-through functions, middle-man and trivial classes,
  single-implementation abstractions, useless overrides and try/except, trivial accessors,
  unused imports and exceptions.
  All languages: duplication, commented-out code, unused dependencies, route detection.
- Functional size from entry points (routes, commands, scripts, agent tools, triggers) or
  public API, in app or library mode, detected automatically.
- Optional LLM second opinion (Anthropic, OpenAI-compatible, Azure OpenAI) on a digest of
  the project, never full source files.
- GitHub Action: job summary, `score` / `answer` / `report` / `json` outputs, `fail-above`
  gate, `exclude` and `mode` inputs; tested on Linux, macOS and Windows runners.
- Text, Markdown and JSON reports; `[tool.code-bloat-review]` in `pyproject.toml`;
  `# bloat: ignore` suppressions.
