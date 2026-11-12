import textwrap
from pathlib import Path

import pytest

from code_bloat_review import review, scan


def write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip("\n"))
    return root


@pytest.fixture
def run(tmp_path):
    """Write a throwaway project and review it: run({"app.py": "..."}, mode="app")."""

    def _run(files: dict[str, str], **options):
        return review(scan(write(tmp_path, files)), **options)

    return _run


def found(report, rule: str | None = None) -> set[str]:
    return {f.symbol for f in report.findings if rule is None or f.rule == rule}
