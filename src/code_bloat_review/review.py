"""Run every check, then turn the evidence into one answer.

The yardstick is Clean Code (see clean_code.py). Score (0-100, higher = more bloat) is a
weighted mean of components in [0, 1]:

* removable   - lines that Clean Code heuristics say should not exist, as a share of
                production SLOC (30 % or more saturates the component)
* density     - production SLOC per capability point vs. a baseline, on a log scale
                (1x baseline -> 0, 8x -> 1); the LLM estimate is averaged in when used
* unused_deps - share of declared runtime dependencies nobody uses (G12 Clutter)

Many small files, classes or functions are *not* penalised: Clean Code asks for them.

Components that cannot be measured (e.g. no capability detected) are left out and the
remaining weights are renormalised.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable

from .clean_code import reference
from .generic import commented_out_code, duplicate_code, regex_capabilities, unused_dependencies
from .llm import LLMError, build_digest
from .models import Capability, Finding, Project, Report
from .pyrules import PyIndex, public_api, python_capabilities, python_findings

WEIGHTS = {"removable": 0.70, "density": 0.25, "unused_deps": 0.05}
CAPABILITY_WEIGHTS = {
    "http-route": 1.0,
    "cli-command": 1.0,
    "script": 1.0,
    "trigger": 1.0,
    "task": 1.0,
    "agent-tool": 1.0,
    "public-api": 0.5,
    "cli-option": 0.25,
    "data-model": 0.25,
}
APP_KINDS = {"http-route", "cli-command", "script", "trigger", "task", "agent-tool"}
VERDICTS = (
    (25, "lean", "NO"),
    (45, "acceptable", "NO"),
    (65, "inflated", "PARTLY"),
    (math.inf, "bloated", "YES"),
)
SUPPRESS = "bloat: ignore"


def review(
    project: Project,
    mode: str = "auto",
    baseline: float = 100.0,
    judge: Callable[[str], dict] | None = None,
) -> Report:
    notes = list(project.notes)
    python = [f for f in project.files if f.language == "python"]
    index = PyIndex(python, project.texts)

    capabilities = python_capabilities(index, project.texts) + regex_capabilities(project)
    if mode == "auto":
        mode = "app" if any(c.kind in APP_KINDS for c in capabilities) else "library"
    if mode == "library":
        capabilities += public_api(index)

    dep_findings, declared = unused_dependencies(project, index.imports)
    findings = [
        *python_findings(index, mode),
        *duplicate_code(project.prod),
        *commented_out_code(project.prod),
        *dep_findings,
    ]
    for finding in findings:
        finding.clean_code = reference(finding.rule)
    sources = {p: t.splitlines() for p, t in project.texts.items()} | {
        f.path: f.lines for f in project.files
    }
    findings = [f for f in findings if not _suppressed(sources.get(f.path, []), f.line)]
    removable = _measure(project, findings)

    prod_sloc = sum(f.sloc for f in project.prod)
    points = sum(CAPABILITY_WEIGHTS[c.kind] for c in capabilities)
    per_point = prod_sloc / points if points else None
    components: dict[str, float] = {}
    if prod_sloc:
        components["removable"] = _clamp(removable / prod_sloc / 0.30)
    if per_point is not None:
        components["density"] = _clamp(math.log2(max(per_point / baseline, 1)) / 3)
    else:
        notes.append(
            "No entry points or public API detected, so functional size is unknown; "
            "density is left out of the score (try --llm)."
        )
    if points and points < 3:
        notes.append(
            f"Only {points:g} capability points detected; density is a coarse signal here."
        )
    if declared:
        components["unused_deps"] = _clamp(len(dep_findings) / declared / 0.5)

    opinion = None
    if judge is not None and prod_sloc:
        try:
            opinion = judge(build_digest(project, capabilities, findings))
        except LLMError as exc:
            notes.append(f"LLM opinion unavailable: {exc}")
        else:
            llm_density = _clamp(math.log2(max(prod_sloc / opinion["lean_sloc_estimate"], 1)) / 3)
            static = components.get("density")
            components["density"] = llm_density if static is None else (static + llm_density) / 2

    if not any(f.language == "python" for f in project.prod) and project.prod:
        notes.append(
            "Structural rules cover Python; other languages get duplication, "
            "dependency and density checks only."
        )

    weights = {k: w for k, w in WEIGHTS.items() if k in components}
    total = sum(weights.values())
    score = (
        round(100 * sum(components[k] * w for k, w in weights.items()) / total, 1) if total else 0.0
    )
    verdict, answer = next((v, a) for limit, v, a in VERDICTS if score < limit)
    by_language: dict[str, int] = defaultdict(int)
    for f in project.prod:
        by_language[f.language] += f.sloc
    return Report(
        root=str(project.root),
        mode=mode,
        answer=answer,
        verdict=verdict,
        score=score,
        components={k: round(v, 3) for k, v in components.items()},
        weights=weights,
        prod_sloc=prod_sloc,
        test_sloc=sum(f.sloc for f in project.files if f.is_test),
        files=len(project.prod),
        sloc_by_language=dict(sorted(by_language.items(), key=lambda kv: -kv[1])),
        capability_points=points,
        capabilities=_sorted(capabilities),
        sloc_per_point=round(per_point, 1) if per_point is not None else None,
        baseline=baseline,
        removable_sloc=removable,
        findings=sorted(findings, key=lambda f: (-f.removable, f.path, f.line)),
        llm=opinion,
        notes=notes,
    )


def _measure(project: Project, findings: list[Finding]) -> int:
    """Fill in each finding's removable lines; return the total without double counting.

    Removable lines are SLOC, except for commented-out code (C5), whose comment lines
    are exactly what would go.
    """
    code = {f.path: f.code_lines for f in project.files}
    union: dict[str, set[int]] = defaultdict(set)
    for finding in findings:
        lines = {n for a, b in finding.ranges for n in range(a, b + 1)}
        if finding.rule != "commented-out-code":
            lines &= code.get(finding.path, set())
        finding.removable = len(lines)
        union[finding.path] |= lines
    return sum(len(lines) for lines in union.values())


def _suppressed(lines: list[str], line: int) -> bool:
    """``# bloat: ignore`` on the reported line, or the line above it, silences a finding."""
    return any(SUPPRESS in text for text in lines[max(line - 2, 0) : line])


def _sorted(capabilities: list[Capability]) -> list[Capability]:
    return sorted(capabilities, key=lambda c: (-CAPABILITY_WEIGHTS[c.kind], c.kind, c.path, c.line))


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)
