"""Find source files, classify them (language, test or production) and count SLOC."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import warnings
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path

from .models import Project, SourceFile

# fmt: off
LANGUAGES = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".go": "go", ".java": "java", ".kt": "kotlin", ".scala": "scala", ".cs": "csharp",
    ".rs": "rust", ".swift": "swift", ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp",
    ".hpp": "cpp", ".rb": "ruby", ".php": "php", ".sh": "shell", ".bash": "shell",
    ".ps1": "powershell", ".tf": "terraform",
}
HASH_COMMENTS = {"python", "ruby", "shell", "powershell"}
MIXED_COMMENTS = {"php", "terraform"}  # both '#' and '//' / '/* */'

# Non-source files kept as text: they can reference code (entry points, handlers,
# templates) and declare or invoke dependencies.
TEXT_SUFFIXES = {".toml", ".cfg", ".ini", ".yaml", ".yml", ".json", ".html", ".jinja", ".j2",
                 ".css", ".scss", ".less", ".vue", ".svelte", ".astro"}
TEXT_NAMES = {"Dockerfile", "Procfile", "Makefile", "requirements.txt", "requirements.in"}

# Not production code: dependencies, build output, generated code, examples and docs.
SKIP_DIRS = {
    "node_modules", "venv", "env", "__pycache__", "build", "dist", "site-packages", "vendor",
    "third_party", "coverage", "htmlcov", "target", "bin", "obj", "migrations",
    "alembic", "examples", "example", "samples", "docs", "doc", "benchmarks",
}
SKIP_FILES = ("*.min.js", "*_pb2.py", "*_pb2_grpc.py", "*.d.ts")
MAX_BYTES = 1_000_000  # larger files are almost always generated

TEST_DIRS = {"test", "tests", "__tests__", "testing", "spec", "specs", "e2e"}
TEST_NAME = re.compile(
    r"^(test_.*\.py|.*_test\.(py|go)|conftest\.py|.*\.(test|spec)\.[cm]?[jt]sx?|.*Tests?\.(java|kt|cs))$"
)
# fmt: on


def scan(root: Path, exclude: Iterable[str] = ()) -> Project:
    project = Project(root=root)
    patterns = tuple(exclude)
    for rel in _candidate_paths(root):
        if _skipped(rel, patterns):
            continue
        path = root / rel
        try:
            if not path.is_file() or path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        language = LANGUAGES.get(path.suffix)
        if language:
            project.files.append(_source_file(rel, language, text, project.notes))
        elif "/" not in rel and path.name.lower().startswith("readme"):
            project.readme = text
        elif path.suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES:
            project.texts[rel] = text
    return project


def is_test_path(rel: str) -> bool:
    *dirs, name = rel.split("/")
    return any(d in TEST_DIRS for d in dirs) or bool(TEST_NAME.match(name))


def line_of(text: str, needle: str) -> int:
    """1-based number of the first line containing ``needle`` (1 if absent)."""
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    return 1


def docstring_nodes(tree: ast.AST) -> list[ast.Constant]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                found.append(first.value)
    return found


def _candidate_paths(root: Path) -> list[str]:
    """Files git would track (honours .gitignore); a plain directory walk otherwise."""
    try:
        listed = subprocess.run(
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                "-C",
                str(root),
                "ls-files",
                "-co",
                "--exclude-standard",
                "-z",
            ],
            capture_output=True,
            check=True,
            timeout=60,
        ).stdout.decode("utf-8", "replace")
        paths = [p for p in listed.split("\0") if p]
        if paths:
            return sorted(paths)
    except (OSError, subprocess.SubprocessError):
        pass
    paths = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") or d == ".github"]
        paths += [Path(dirpath, name).relative_to(root).as_posix() for name in filenames]
    return sorted(paths)


def _skipped(rel: str, patterns: tuple[str, ...]) -> bool:
    *dirs, name = rel.split("/")
    if any(
        d in SKIP_DIRS or d.endswith(".egg-info") or (d.startswith(".") and d != ".github")
        for d in dirs
    ):
        return True
    if any(fnmatch(name, p) for p in SKIP_FILES):
        return True
    return any(fnmatch(rel, p) or rel.startswith(p.rstrip("/*") + "/") for p in patterns)


def _source_file(rel: str, language: str, text: str, notes: list[str]) -> SourceFile:
    lines = text.splitlines()
    code = _code_lines(lines, language)
    tree = None
    if language == "python":
        try:
            with warnings.catch_warnings():  # e.g. invalid escape sequences in reviewed code
                warnings.simplefilter("ignore")
                tree = ast.parse(text, filename=rel)
        except (SyntaxError, ValueError):
            version = f"{sys.version_info.major}.{sys.version_info.minor}"
            notes.append(f"{rel}: not valid Python {version} syntax; counted lines only")
        else:
            for doc in docstring_nodes(tree):
                code -= set(range(doc.lineno, (doc.end_lineno or doc.lineno) + 1))
    return SourceFile(rel, language, is_test_path(rel), lines, code, tree)


def _code_lines(lines: list[str], language: str) -> set[int]:
    hash_comments = language in HASH_COMMENTS or language in MIXED_COMMENTS
    c_comments = language not in HASH_COMMENTS
    code, in_block = set(), False
    for number, raw in enumerate(lines, start=1):
        text = raw.strip()
        if in_block:
            if "*/" not in text:
                continue
            in_block, text = False, text.split("*/", 1)[1].strip()
        if not text or (hash_comments and text.startswith("#")):
            continue
        if c_comments and text.startswith("//"):
            continue
        if c_comments and text.startswith("/*"):
            rest = text[2:]
            if "*/" not in rest:
                in_block = True
                continue
            text = rest.split("*/", 1)[1].strip()
            if not text:
                continue
        code.add(number)
    return code
