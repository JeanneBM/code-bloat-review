import io
import json
import urllib.request

import pytest

from code_bloat_review import llm
from code_bloat_review.models import Capability, Finding, Project, SourceFile

ANSWER = {
    "purpose": "todo app",
    "lean_sloc_estimate": 40,
    "assessment": "too big",
    "capabilities": [{"name": "add", "lean_sloc": 10}],
    "suspects": [{"where": "x", "why": "y"}],
}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def http(monkeypatch):
    """Capture outgoing requests and answer them with a canned provider response."""
    calls = []

    def respond(body):
        def urlopen(request, timeout):
            calls.append(request)
            return FakeResponse(json.dumps(body).encode())

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    respond.calls = calls
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "CBR_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return respond


def test_anthropic_request_shape(http, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    http({"content": [{"type": "text", "text": "Here you go:\n" + json.dumps(ANSWER)}]})
    opinion = llm.make_judge()("digest")
    (request,) = http.calls
    body = json.loads(request.data)
    assert request.full_url == "https://api.anthropic.com/v1/messages"
    assert request.get_header("X-api-key") == "sk-test"
    assert request.get_header("Anthropic-version") == "2023-06-01"
    assert body["model"] == llm.DEFAULT_ANTHROPIC_MODEL and body["system"] == llm.SYSTEM_PROMPT
    assert opinion["lean_sloc_estimate"] == 40 and opinion["model"].startswith("anthropic:")


def test_azure_openai_request_shape(http, monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://my.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "az-key")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-review")
    http({"choices": [{"message": {"content": json.dumps(ANSWER)}}]})
    assert llm.make_judge()("digest")["purpose"] == "todo app"
    (request,) = http.calls
    assert request.full_url == (
        "https://my.openai.azure.com/openai/deployments/gpt-review/chat/completions"
        f"?api-version={llm.AZURE_API_VERSION}"
    )
    assert request.get_header("Api-key") == "az-key"


def test_openai_needs_a_model(http, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    with pytest.raises(llm.LLMError, match="--model"):
        llm.make_judge()
    http({"choices": [{"message": {"content": json.dumps(ANSWER)}}]})
    llm.make_judge(model="some-model")("digest")
    assert http.calls[0].full_url == "https://api.openai.com/v1/chat/completions"


def test_missing_credentials(http):
    with pytest.raises(llm.LLMError, match="no LLM credentials"):
        llm.make_judge()


@pytest.mark.parametrize(
    "text",
    [
        "no json here",
        '{"lean_sloc_estimate": 0}',
        '{"lean_sloc_estimate": "many"}',
        "[1, 2]",
        "{broken",
    ],
)
def test_bad_answers_raise(text):
    with pytest.raises(llm.LLMError):
        llm.assess("digest", lambda system, user: text)


def test_digest_contains_readme_layout_and_outline():
    source = SourceFile(
        "pkg/core.py",
        "python",
        False,
        ["x"],
        {1},
        __import__("ast").parse("class Engine(Base):\n    def run(self, n): ...\n"),
    )
    project = Project(root=None, files=[source], readme="# Engine\nDoes things.")
    digest = llm.build_digest(
        project,
        [Capability("cli-command", "run", "pkg/core.py", 2)],
        [Finding("dead-code", "pkg/core.py", 1, "Engine", "never referenced", removable=3)],
    )
    for expected in (
        "# Engine",
        "1  pkg/core.py",
        "cli-command: run",
        "dead-code pkg/core.py:1",
        "class Engine(Base): run",
    ):
        assert expected in digest
