# code-bloat-review

> **„Czy ten kod jest nieproporcjonalnie rozbudowany względem tego, co robi?”**
> *Is this code disproportionately large for what it does?*

`code-bloat-review` answers that one question for a whole project: **YES / PARTLY / NO**,
with a 0–100 score and the evidence behind it. The yardstick is
**Clean Code** (Robert C. Martin): every finding is a Clean Code heuristic, and "lean"
means what Clean Code asks for, not the fewest characters.

- Zero runtime dependencies (Python ≥ 3.11 standard library only)
- Deep AST rules for Python. Duplication, commented-out code, dependency checks and
  route/command detection for JS/TS, Go, Java/Kotlin, C#, PHP and Ruby
- Text for humans, Markdown for PR comments and job summaries, JSON for agents and pipelines
- Optional LLM second opinion (Anthropic, OpenAI-compatible, Azure OpenAI) on *what the code does*
- A GitHub Action, and a CI gate (`--fail-above`)

## Quick start

```bash
pip install git+https://github.com/JeanneBM/code-bloat-review
code-bloat-review path/to/project
```

The repo ships the same to-do CLI twice. [`examples/lean_todo`](examples/lean_todo/todo.py)
is 31 SLOC. [`examples/bloated_todo`](examples/bloated_todo/todo_app) has identical
behaviour, written "enterprise style" (interfaces, factories, services, accessors):

```text
$ code-bloat-review examples/bloated_todo --top 6
Is this code disproportionately large for what it does?  →  YES  (bloated, 73.7/100)

  Yardstick  Clean Code (R. C. Martin): G5, F4/G9, C5, G12, ch. 6, 7 and 12 Simple Design
  Size       169 SLOC in 11 production files (python 169); 0 SLOC of tests
  Does       4.75 capability points: 3 cli-command, 2 cli-option, 1 script, 1 data-model [mode: app]
  Density    35.6 SLOC per capability point (baseline 100, 0.4x)
  Removable  ~80 lines (47% of SLOC) break Clean Code heuristics and could go without changing behaviour
  Score      removable 1.00 x 0.70 + density 0.00 x 0.25

Bloat drivers
  rule                     Clean Code                         findings  removable lines  what it means
  dead-code                F4 Dead Function / G9 Dead Code    8         30               defined but never referenced (or only from tests)
  trivial-accessor         Ch.6 Data Abstraction              6         12               get_x/set_x around a plain attribute
  duplicate-code           G5 Duplication                     2         12               block repeated elsewhere in the project
  useless-try              G12 Clutter                        2         6                try/except that only re-raises
  single-impl-abstraction  Ch.12 Simple Design #4             1         5                abstract base with one implementation and no test double
  commented-out-code       C5 Commented-Out Code              1         4                code kept in comments; version control remembers it
  ...

Top findings (6 of 28)
  where                      rule                     symbol                     lines  why
  todo_app/utils.py:15       dead-code                retry                      12     function is never referenced
  todo_app/cli.py:31         duplicate-code           lines 31-36                6      repeats todo_app/cli.py:21
  todo_app/repository.py:11  single-impl-abstraction  AbstractTaskRepository     5      abstract base with a single implementation (JsonTaskRepository) and no test double
  ...

$ code-bloat-review examples/lean_todo
Is this code disproportionately large for what it does?  →  NO  (lean, 0/100)
```

## How the answer is built

The tool weighs two sides of the question against each other, then checks what could go.

**1. How big is it?** Production SLOC: blank lines, comments and docstrings don't count.
Tests are reported separately. `.gitignore` is honoured, and dependencies, build output,
generated code (`*_pb2.py`, `*.min.js`, `*.d.ts`), migrations, `examples/`, `docs/`
and `benchmarks/` are skipped.

**2. What does it do?** *Capability points*: things the project offers its users.

| Detected | Points | Examples |
|---|---|---|
| HTTP route | 1 | FastAPI/Flask/Starlette decorators, `add_api_route`, Django `urls.py`, Express, Go `HandleFunc`/gin, Spring `@GetMapping`, ASP.NET, Laravel, Sinatra |
| CLI command, script | 1 | argparse sub-parsers, click/typer commands, `[project.scripts]`, `__main__`, package.json `bin`, commander, cobra |
| Agent tool | 1 | `@mcp.tool()`, `@tool`, `@function_tool`, `@kernel_function` |
| Trigger, task | 1 | Azure Functions `@app.*_trigger`, Celery `@task` / `@shared_task` |
| Public API (libraries) | 0.5 | public functions and methods |
| CLI option, data model | 0.25 | `add_argument`, click options, typer parameters, Pydantic / dataclass / ORM models |

The mode is detected automatically: **app** when entry points exist, otherwise **library**.
In a library, public code is API, so it is never called dead. Override it with `--mode`.

**3. What could go?** The Clean Code rules below. Each finding covers the lines that
would disappear. These are summed without double counting (a dead class that is also a
middle man counts once).

### Score

| Component | Weight | Meaning |
|---|---|---|
| `removable` | 0.70 | removable lines ÷ production SLOC; 30 % or more saturates |
| `density` | 0.25 | SLOC per capability point vs `--baseline` (default 100), log scale: 1× → 0, 8× → 1. With `--llm`, averaged with *actual ÷ lean estimate* |
| `unused_deps` | 0.05 | share of declared runtime dependencies nobody uses |

A component that can't be measured (no entry points found, no manifest) is left out, and
the remaining weights are renormalised.

| Score | Verdict | Answer |
|---|---|---|
| < 25 | lean | **NO** |
| 25–45 | acceptable | **NO** |
| 45–65 | inflated | **PARTLY** |
| ≥ 65 | bloated | **YES** |

## The yardstick: Clean Code

Every rule enforces a heuristic from *Clean Code* (chapter 17 "Smells and Heuristics",
plus chapters 6, 7 and 12). The reference is shown in every report and stored in every
JSON finding (`clean_code`).

| Rule | Clean Code | Flags | Deliberately left alone |
|---|---|---|---|
| `duplicate-code` | **G5** Duplication | ≥ 6 identical normalised lines anywhere in production code | imports, closing brackets/tags, multi-line `def` signatures, tests |
| `dead-code` | **F4** Dead Function, **G9** Dead Code | functions, classes, methods never referenced, or referenced only from tests (apps) | decorated code, dunder/sunder/visitor hooks, subclasses of framework classes, file-like protocol methods, `main`/`handler`/`setup`; public API in libraries; names used in strings or config (`pyproject.toml`, YAML, templates) |
| `commented-out-code` | **C5** Commented-Out Code | comment blocks that parse as Python, or look like `//` statements | prose with an embedded example, directives (`type:`, `noqa`, `TODO`, `eslint` …) |
| `unused-import` | **G12** Clutter | imported names a module never uses | `__init__.py` re-exports, `import x as x`, `__future__`, `# noqa` |
| `unused-dependency` | **G12** Clutter | runtime deps (pyproject, requirements, package.json) never imported or invoked | servers/drivers used without import (uvicorn, psycopg …), tooling, pip-compile lockfiles, names used in Dockerfile/CI/CSS |
| `useless-override` | **G12** Clutter | a method that only calls `super()` with the same arguments | |
| `pass-through` | **G12** Clutter | a function that only forwards its own parameters to another callable | decorated functions, zero-argument factories, public aliases in libraries |
| `useless-try` | **G12** Clutter | `try`/`except` whose every handler only re-raises | handlers that log or convert, `finally`/`else` |
| `middle-man` | **Ch.12** Simple Design rule 4 (minimal classes and methods) | classes where ≥ half of the methods (min. 2) only delegate to one `self.attr` | proxies implementing a file-like protocol, framework subclasses |
| `single-impl-abstraction` | **Ch.12** Simple Design rule 4 | ABC/interface with ≤ 1 production implementation | interfaces with a **test double** (a seam for tests is a reason to exist), `Protocol`s, null objects, plugin/extension bases, public bases in libraries |
| `trivial-class` | **Ch.12** Simple Design rule 4 | `__init__` plus one method: a function would do | several classes sharing that method (interchangeable strategies), dataclasses, subclassed classes |
| `trivial-accessor` | **Ch.6** Data Abstraction | `get_x`/`set_x` that only read or write `self.x` | accessors with logic, `@property` |
| `unused-exception` | **Ch.7** Define exception classes in terms of a caller's needs | custom exception classes raised but never caught or checked by name | exceptions with their own fields, public exceptions in libraries |

**What is *not* bloat under Clean Code.** Small functions and classes, and many small
files, are what chapters 3 and 10 ask for, so nothing in the score penalises them.
Tests, an interface that has a test double, intention-revealing helpers with real logic,
named constants: all fine.

**Readability heuristics are out of scope.** F1 Too Many Arguments, F3 Flag Arguments,
G25 Magic Numbers, G30 Functions Should Do One Thing and the N-rules for names are about how readable
code is, not how much of it there is. Use a linter for those. This tool judges size
against behaviour.

## LLM second opinion (optional)

Static analysis measures code precisely but can only estimate *what it does*. With
`--llm`, a model reads a **digest** of the project: README excerpt, file list with SLOC,
detected capabilities, findings and code signatures. It **never** sees full source files.
It is asked how many SLOC a *Clean Code implementation of the same features* would need.
`density` then averages the static estimate with *actual SLOC ÷ that estimate*, and the
report shows the model's purpose summary, assessment and suspects, each tagged with the
heuristic it breaks.

| Provider | Environment |
|---|---|
| Anthropic (default when its key is set) | `ANTHROPIC_API_KEY`; model `--model`/`CBR_MODEL`, default `claude-sonnet-5-5` |
| Azure OpenAI | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT` (or `--model`), optional `AZURE_OPENAI_API_VERSION` |
| OpenAI or any compatible endpoint | `OPENAI_API_KEY`, `--model`/`CBR_MODEL`, optional `OPENAI_BASE_URL` |

```bash
code-bloat-review . --llm                 # first provider with credentials
code-bloat-review . --llm azure           # explicit provider
```

LLM output varies from run to run, so gate CI on the static score and use `--llm` for reviews.

## Usage

```text
code-bloat-review [PATH] [-f text|markdown|json] [-o FILE] [--top N]
                  [--mode auto|app|library] [--exclude GLOB]... [--baseline SLOC]
                  [--fail-above SCORE] [--llm [auto|anthropic|openai|azure]] [--model NAME]
```

- `--fail-above SCORE` exits with status 1 when the score is higher: use it as a CI gate.
- `-f markdown` writes a PR-comment-ready report. `-f json` writes everything (findings,
  capabilities, components) for scripts and agents.
- Settings can live in the reviewed project's `pyproject.toml`:

  ```toml
  [tool.code-bloat-review]
  exclude = ["legacy/*", "scripts/one_off_*.py"]
  mode = "app"          # auto | app | library
  baseline = 100        # SLOC per capability point considered normal
  fail-above = 45
  ```

- Silence a finding you accept with `# bloat: ignore` on the reported line or the line
  above it.

### GitHub Action

```yaml
- uses: actions/checkout@v5
- id: bloat
  uses: JeanneBM/code-bloat-review@main
  with:
    path: .
    fail-above: "45"
    args: "--exclude 'legacy/*'"
# outputs: steps.bloat.outputs.score / answer / report (Markdown file path)
```

The Markdown report is added to the job summary automatically.

## Tried on real projects

Default settings, November 2026:

| Project | SLOC | Answer | Score | What drives it |
|---|---|---|---|---|
| [pallets/click](https://github.com/pallets/click) `8abb77a` (library) | 7,107 | NO, lean | 1.3 | a few duplicated blocks |
| [httpie/cli](https://github.com/httpie/cli) `5b604c3` | 7,588 | NO, lean | 16.9 | a 90-line function nobody calls, commented-out debug lines |
| [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template) `aabb901` | 9,324 | NO, acceptable | 31.7 | copy-pasted form components (Add/Edit User/Item) |
| `examples/lean_todo` | 31 | NO, lean | 0 | |
| `examples/bloated_todo` | 169 | **YES**, bloated | 73.7 | dead code, accessors, duplication, single-implementation interface |

The tool also reviews itself in CI (`fail-above = 25` in this repo's `pyproject.toml`).

## Limitations

- **References are matched by name**, without type inference: any use of `save` keeps
  every `save` method alive. That costs some missed dead code in exchange for very few
  false alarms. Code reached only through computed names (`getattr(obj, f"do_{x}")`) or
  naming conventions the tool doesn't know can look dead: use `# bloat: ignore` or `--exclude`.
- The structural rules (dead code, abstractions, accessors …) are **Python-only**.
  Other languages get duplication, `//` commented-out code, npm dependencies and route detection.
- **Density is a prior**, not a measurement. 100 SLOC per capability point is a reasonable
  middle for services and CLIs. Tune `--baseline`, or add `--llm`.
- **Removable lines are an estimate.** Every repeated copy of a duplicate counts; a dead
  function counts fully. Treat findings as review leads, not automatic deletions.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q && ruff check . && ruff format --check .
code-bloat-review .        # the tool must stay lean by its own standard
```

```
src/code_bloat_review/
  scan.py         files, languages, test/production split, SLOC
  pyrules.py      Python index, Clean Code rules, capability detection
  generic.py      duplication, commented-out code, dependencies, non-Python routes
  clean_code.py   the yardstick: rule -> Clean Code heuristic
  review.py       scoring and verdict
  llm.py          optional LLM estimate (urllib, no SDKs)
  report.py       text / Markdown / JSON
  cli.py          command line
```
