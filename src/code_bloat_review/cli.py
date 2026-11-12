"""Command line: ``code-bloat-review [PATH] [options]``."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from .llm import LLMError, make_judge
from .report import QUESTION, render
from .review import review
from .scan import scan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="code-bloat-review", description=QUESTION)
    parser.add_argument("path", nargs="?", default=".", help="project directory (default: .)")
    parser.add_argument("-f", "--format", choices=("text", "markdown", "json"), default="text")
    parser.add_argument("-o", "--output", help="write the report to this file instead of stdout")
    parser.add_argument(
        "--top", type=int, default=15, help="how many findings to list (default 15)"
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "app", "library"),
        help="app: unused public code is dead; library: public code is API",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="skip matching paths (repeatable), e.g. 'legacy/*'",
    )
    parser.add_argument(
        "--baseline", type=float, help="SLOC per capability point considered normal (default 100)"
    )
    parser.add_argument(
        "--fail-above",
        type=float,
        metavar="SCORE",
        help="exit with status 1 when the score is above SCORE (for CI)",
    )
    parser.add_argument(
        "--llm",
        nargs="?",
        const="auto",
        choices=("auto", "anthropic", "openai", "azure"),
        help="ask an LLM to estimate the size of a lean implementation",
    )
    parser.add_argument("--model", help="LLM model, or Azure deployment name (env: CBR_MODEL)")
    args = parser.parse_args(argv)

    root = Path(args.path).resolve()
    if not root.is_dir():
        parser.error(f"not a directory: {root}")
    config = _config(root)
    judge = None
    if args.llm:
        try:
            judge = make_judge(args.llm, args.model)
        except LLMError as exc:
            parser.error(str(exc))

    project = scan(root, [*config.get("exclude", []), *args.exclude])
    report = review(
        project,
        mode=args.mode or config.get("mode", "auto"),
        baseline=args.baseline or float(config.get("baseline", 100)),
        judge=judge,
    )
    output = render(report, args.format, args.top)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        sys.stdout.write(output + "\n")
    fail_above = args.fail_above if args.fail_above is not None else config.get("fail-above")
    return 1 if fail_above is not None and report.score > float(fail_above) else 0


def _config(root: Path) -> dict:
    """``[tool.code-bloat-review]`` from the reviewed project's pyproject.toml, if any."""
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return data.get("tool", {}).get("code-bloat-review", {})
