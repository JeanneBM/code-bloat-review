"""Render a Report as terminal text, Markdown (PR comments, job summaries) or JSON."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict

from .clean_code import meaning, reference
from .models import Report

QUESTION = "Is this code disproportionately large for what it does?"
YARDSTICK = "Clean Code (R. C. Martin): G5, F4/G9, C5, G12, ch. 6, 7 and 12 Simple Design"


def render(report: Report, fmt: str = "text", top: int = 15) -> str:
    if fmt == "json":
        return json.dumps(asdict(report), indent=2)
    blocks = _blocks(report, top)
    if fmt == "markdown":
        head = [
            f"## code-bloat-review: **{report.answer}** ({report.verdict}, {report.score:g}/100)",
            f"> {QUESTION}",
            "",
        ]
        return "\n".join(head + [line for block in blocks for line in _markdown(*block)]).rstrip()
    head = [
        f"code-bloat-review · {report.root}",
        f"{QUESTION}  →  {report.answer}  ({report.verdict}, {report.score:g}/100)",
        "",
    ]
    return "\n".join(head + [line for block in blocks for line in _text(*block)]).rstrip()


def _blocks(report: Report, top: int) -> list[tuple[str, list[str], list[tuple]]]:
    """(title, headers, rows) triples; empty headers mean a key/value or plain-text block."""
    blocks = [("", [], _summary(report))]
    drivers: dict[str, list[int]] = {}
    for f in report.findings:
        count = drivers.setdefault(f.rule, [0, 0])
        count[0] += 1
        count[1] += f.removable
    if drivers:
        rows = [
            (rule, reference(rule), n, sloc, meaning(rule))
            for rule, (n, sloc) in sorted(drivers.items(), key=lambda kv: (-kv[1][1], -kv[1][0]))
        ]
        blocks.append(
            (
                "Bloat drivers",
                ["rule", "Clean Code", "findings", "removable lines", "what it means"],
                rows,
            )
        )
        shown = report.findings[: max(top, 0)]
    if drivers and shown:
        blocks.append(
            (
                f"Top findings ({len(shown)} of {len(report.findings)})",
                ["where", "rule", "symbol", "lines", "why"],
                [(f"{f.path}:{f.line}", f.rule, f.symbol, f.removable, f.message) for f in shown],
            )
        )
    if report.llm:
        opinion = report.llm
        lines = [f"Purpose: {opinion['purpose']}", f"Assessment: {opinion['assessment']}"]
        lines += [
            f"- {c.get('name', '?')}: ~{c.get('lean_sloc', '?')} SLOC"
            for c in opinion["capabilities"]
        ]
        lines += [
            f"Suspect: {s.get('where', '?')} [{s.get('rule', '-')}]: {s.get('why', '')}"
            for s in opinion["suspects"]
        ]
        blocks.append((f"LLM opinion ({opinion['model']})", [], [(line,) for line in lines]))
    if report.notes:
        blocks.append(("Notes", [], [(f"- {note}",) for note in report.notes]))
    return blocks


def _summary(report: Report) -> list[tuple]:
    languages = ", ".join(f"{lang} {sloc:,}" for lang, sloc in report.sloc_by_language.items())
    kinds = Counter(c.kind for c in report.capabilities).most_common()
    does = ", ".join(f"{n} {kind}" for kind, n in kinds) or "nothing detected"
    share = report.removable_sloc / report.prod_sloc if report.prod_sloc else 0
    rows = [
        ("Yardstick", YARDSTICK),
        (
            "Size",
            f"{report.prod_sloc:,} SLOC in {report.files} production files ({languages or '-'}); "
            f"{report.test_sloc:,} SLOC of tests",
        ),
        ("Does", f"{report.capability_points:g} capability points: {does} [mode: {report.mode}]"),
        (
            "Density",
            "unknown"
            if report.sloc_per_point is None
            else f"{report.sloc_per_point:g} SLOC per capability point "
            f"(baseline {report.baseline:g}, {report.sloc_per_point / report.baseline:.1f}x)",
        ),
        (
            "Removable",
            f"~{report.removable_sloc:,} lines ({share:.0%} of SLOC) break Clean Code heuristics "
            "and could go without changing behaviour",
        ),
    ]
    if report.llm:
        lean = report.llm["lean_sloc_estimate"]
        rows.append(
            (
                "LLM",
                f"a lean version would be ~{lean:,} SLOC; this code is "
                f"{report.prod_sloc / lean:.1f}x that",
            )
        )
    parts = [
        f"{name} {report.components[name]:.2f} x {weight:.2f}"
        for name, weight in report.weights.items()
    ]
    rows.append(("Score", " + ".join(parts) or "-"))
    return rows


def _text(title: str, headers: list[str], rows: list[tuple]) -> list[str]:
    lines = [title] if title else []
    if headers or (rows and len(rows[0]) == 2):
        table = [tuple(headers), *rows] if headers else rows
        widths = [max(len(str(row[i])) for row in table) for i in range(len(table[0]) - 1)]
        lines += [
            "  "
            + "  ".join(str(c).ljust(w) for c, w in zip(row, widths, strict=False))
            + "  "
            + str(row[-1])
            for row in table
        ]
    else:
        lines += [f"  {row[0]}" for row in rows]
    return [*lines, ""]


def _markdown(title: str, headers: list[str], rows: list[tuple]) -> list[str]:
    lines = [f"### {title}", ""] if title else []
    if headers or (rows and len(rows[0]) == 2):
        cells = headers or ["", ""]
        lines += ["| " + " | ".join(cells) + " |", "|" + "---|" * len(cells)]
        lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    else:
        lines += [str(row[0]) for row in rows]
    return [*lines, ""]


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
