"""Plain data passed between the scanner, the rules, the scoring and the renderers."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SourceFile:
    path: str  # POSIX path relative to the project root
    language: str
    is_test: bool
    lines: list[str]
    code_lines: set[int]  # 1-based numbers of lines that count as SLOC
    tree: ast.Module | None = None  # parsed once for Python files

    @property
    def sloc(self) -> int:
        return len(self.code_lines)


@dataclass
class Project:
    root: Path
    files: list[SourceFile] = field(default_factory=list)
    texts: dict[str, str] = field(default_factory=dict)  # configs, manifests, templates
    readme: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def prod(self) -> list[SourceFile]:
        return [f for f in self.files if not f.is_test]


@dataclass(frozen=True)
class Capability:
    """Something the project does for its users: a route, a command, an agent tool..."""

    kind: str
    name: str
    path: str
    line: int


@dataclass
class Finding:
    """Code that could go (or shrink) without changing what the project does."""

    rule: str
    path: str
    line: int
    symbol: str
    message: str
    ranges: tuple[tuple[int, int], ...] = ()  # line ranges that would disappear
    removable: int = 0  # SLOC inside ``ranges``; filled in by the review
    clean_code: str = ""  # the Clean Code heuristic the finding enforces


@dataclass
class Report:
    root: str
    mode: str
    answer: str  # YES / PARTLY / NO
    verdict: str  # lean / acceptable / inflated / bloated
    score: float
    components: dict[str, float]
    weights: dict[str, float]
    prod_sloc: int
    test_sloc: int
    files: int
    sloc_by_language: dict[str, int]
    capability_points: float
    capabilities: list[Capability]
    sloc_per_point: float | None
    baseline: float
    removable_sloc: int
    findings: list[Finding]
    llm: dict | None = None
    notes: list[str] = field(default_factory=list)
