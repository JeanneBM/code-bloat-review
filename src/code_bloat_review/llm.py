"""Optional second opinion from an LLM: how big would a lean version of this project be?

Static analysis can count code precisely but only guesses what the code *does*. An LLM
reads the README, the file layout and the signatures and estimates the size of a clean
implementation of the same features. Only that digest is sent, never full source files.
Plain ``urllib`` keeps the tool dependency-free; Anthropic, OpenAI (or any compatible
endpoint) and Azure OpenAI are supported.
"""

from __future__ import annotations

import ast
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable

from .models import Capability, Finding, Project

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"
AZURE_API_VERSION = "2024-10-21"
DIGEST_LIMIT = 30_000  # characters

SYSTEM_PROMPT = """You review software projects for over-engineering, using Robert C. Martin's
Clean Code as the yardstick. You get a digest of a project: README excerpt, production files
with their SLOC, detected entry points, static findings and an outline of the code.
Estimate how many production SLOC (no tests, blank lines or comments) a Clean Code
implementation of the SAME functionality would need: small functions with intention-revealing
names, no duplication (G5), no dead code (G9), no clutter (G12), no speculative abstractions
(Simple Design rule 4), reasonable error handling. Clean Code favours small functions and
classes, so do not count them as bloat. Be concrete and conservative. Reply with JSON only."""

ANSWER_FORMAT = """
Reply with ONE JSON object and nothing else:
{
  "purpose": "<one sentence: what the project does>",
  "capabilities": [{"name": "<feature>", "lean_sloc": <int>}],
  "lean_sloc_estimate": <int, total production SLOC of a lean implementation>,
  "assessment": "<2-4 sentences: is the code disproportionately large for what it does, and why>",
  "suspects": [{"where": "<file or module>", "rule": "<Clean Code heuristic, e.g. G5>",
                "why": "<what looks over-engineered>"}]
}"""


class LLMError(RuntimeError):
    pass


Ask = Callable[[str, str], str]  # (system prompt, user prompt) -> model text


def make_judge(
    provider: str = "auto", model: str | None = None, timeout: float = 120
) -> Callable[[str], dict]:
    """A function that takes a digest and returns the LLM's opinion as a dict."""
    provider = _detect_provider(provider)
    model = model or os.environ.get("CBR_MODEL")
    if provider == "anthropic":
        model = model or DEFAULT_ANTHROPIC_MODEL
        url = (
            os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
            + "/v1/messages"
        )
        headers = {"x-api-key": _env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"}

        def payload(system: str, user: str) -> dict:
            return {
                "model": model,
                "max_tokens": 2000,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }

        def text_of(data: dict) -> str:
            return "".join(
                b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
            )
    else:
        if provider == "azure":
            model = model or _env("AZURE_OPENAI_DEPLOYMENT")
            version = os.environ.get("AZURE_OPENAI_API_VERSION", AZURE_API_VERSION)
            url = (
                f"{_env('AZURE_OPENAI_ENDPOINT').rstrip('/')}/openai/deployments/{model}"
                f"/chat/completions?api-version={version}"
            )
            headers = {"api-key": _env("AZURE_OPENAI_API_KEY")}
        else:
            if not model:
                raise LLMError("set --model or CBR_MODEL for the OpenAI provider")
            url = (
                os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
                + "/chat/completions"
            )
            headers = {"Authorization": f"Bearer {_env('OPENAI_API_KEY')}"}

        def payload(system: str, user: str) -> dict:
            return {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }

        def text_of(data: dict) -> str:
            try:
                return data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMError(f"unexpected response shape: {str(data)[:200]}") from exc

    def ask(system: str, user: str) -> str:
        return text_of(_post_json(url, headers, payload(system, user), timeout))

    return lambda digest: assess(digest, ask, f"{provider}:{model}")


def assess(digest: str, ask: Ask, label: str = "") -> dict:
    data = _parse_json(ask(SYSTEM_PROMPT, digest + "\n" + ANSWER_FORMAT))
    lean = data.get("lean_sloc_estimate")
    if isinstance(lean, bool) or not isinstance(lean, int | float) or lean <= 0:
        raise LLMError("the answer has no positive lean_sloc_estimate")
    return {
        "model": label,
        "purpose": str(data.get("purpose", "")),
        "lean_sloc_estimate": int(lean),
        "capabilities": [c for c in data.get("capabilities", []) if isinstance(c, dict)][:20],
        "assessment": str(data.get("assessment", "")),
        "suspects": [s for s in data.get("suspects", []) if isinstance(s, dict)][:5],
    }


def build_digest(project: Project, capabilities: list[Capability], findings: list[Finding]) -> str:
    prod = sorted(project.prod, key=lambda f: -f.sloc)
    prod_sloc, test_sloc = (
        sum(f.sloc for f in prod),
        sum(f.sloc for f in project.files if f.is_test),
    )
    parts = [
        "# Project digest",
        f"Production: {prod_sloc} SLOC in {len(prod)} files; tests: {test_sloc} SLOC.",
        "## README (excerpt)",
        project.readme[:3000].strip() or "(none)",
        "## Production files (SLOC)",
        *(f"{f.sloc:6d}  {f.path}" for f in prod[:80]),
        "## Detected entry points and features",
        *(f"- {c.kind}: {c.name} ({c.path}:{c.line})" for c in capabilities[:60]),
        "## Static findings (removable SLOC)",
        *(
            f"- {f.rule} {f.path}:{f.line} {f.symbol}: {f.message} [{f.removable}]"
            for f in sorted(findings, key=lambda f: -f.removable)[:30]
        ),
        "## Code outline",
        *_outline(project),
    ]
    return "\n".join(parts)[:DIGEST_LIMIT]


def _outline(project: Project) -> list[str]:
    lines = []
    for f in project.prod:
        if f.tree is None:
            continue
        lines.append(f"{f.path}:")
        for node in f.tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                lines.append(f"  def {node.name}({ast.unparse(node.args)})")
            elif isinstance(node, ast.ClassDef):
                bases = ", ".join(ast.unparse(b) for b in node.bases)
                methods = [
                    m.name
                    for m in node.body
                    if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef)
                ]
                lines.append(f"  class {node.name}({bases}): {', '.join(methods)}")
    return lines


def _detect_provider(provider: str) -> str:
    if provider != "auto":
        return provider
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("AZURE_OPENAI_ENDPOINT"):
        return "azure"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    raise LLMError(
        "no LLM credentials found: set ANTHROPIC_API_KEY, AZURE_OPENAI_* or OPENAI_API_KEY"
    )


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise LLMError(f"environment variable {name} is not set")
    return value


def _post_json(url: str, headers: dict[str, str], body: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"content-type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise LLMError(f"HTTP {exc.code} from {url.split('?')[0]}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LLMError(f"request to {url.split('?')[0]} failed: {exc}") from exc


def _parse_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise LLMError("the answer contains no JSON object")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"the answer is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMError("the answer is not a JSON object")
    return data
