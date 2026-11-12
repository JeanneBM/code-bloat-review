import json
from pathlib import Path

import pytest
from conftest import write

from code_bloat_review.cli import main

BLOATED = Path(__file__).parent.parent / "examples" / "bloated_todo"


def test_json_output(capsys):
    assert main([str(BLOATED), "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["answer"] == "YES"
    assert {"rule", "path", "line", "symbol", "message", "removable"} <= set(data["findings"][0])


def test_markdown_output_to_file(tmp_path):
    out = tmp_path / "report.md"
    main([str(BLOATED), "-f", "markdown", "-o", str(out), "--top", "3"])
    text = out.read_text()
    assert text.startswith("## code-bloat-review: **YES**")
    assert "| rule | Clean Code | findings | removable lines | what it means |" in text
    assert "| dead-code | F4 Dead Function / G9 Dead Code |" in text
    assert "### Top findings (3 of" in text


def test_text_output(capsys):
    main([str(BLOATED)])
    out = capsys.readouterr().out
    assert "→  YES" in out and "Bloat drivers" in out


def test_fail_above_and_project_config(tmp_path, capsys):
    write(
        tmp_path,
        {
            "app.py": "def unused():\n    return 1\n\nif __name__ == '__main__':\n    print(1)\n",
            "pyproject.toml": "[tool.code-bloat-review]\nfail-above = 10\n",
        },
    )
    assert main([str(tmp_path)]) == 1
    assert main([str(tmp_path), "--fail-above", "99"]) == 0
    write(
        tmp_path,
        {"pyproject.toml": '[tool.code-bloat-review]\nfail-above = 10\nexclude = ["app.py"]\n'},
    )
    assert main([str(tmp_path)]) == 0


def test_rejects_missing_directory(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main([str(tmp_path / "nope")])
    assert exc.value.code == 2


def test_llm_flag_without_credentials_is_a_usage_error(tmp_path, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit) as exc:
        main([str(tmp_path), "--llm"])
    assert exc.value.code == 2
