from pathlib import Path

from conftest import found

from code_bloat_review import review, scan

EXAMPLES = Path(__file__).parent.parent / "examples"


def test_lean_and_bloated_versions_of_the_same_app():
    lean = review(scan(EXAMPLES / "lean_todo"))
    bloated = review(scan(EXAMPLES / "bloated_todo"))
    assert (lean.answer, lean.verdict) == ("NO", "lean")
    assert bloated.answer == "YES"
    assert bloated.prod_sloc > 4 * lean.prod_sloc
    assert bloated.removable_sloc / bloated.prod_sloc > 0.3
    rules = {f.rule for f in bloated.findings}
    assert {
        "dead-code",
        "single-impl-abstraction",
        "middle-man",
        "trivial-class",
        "duplicate-code",
    } <= rules


def test_web_cli_and_agent_capabilities(run):
    report = run(
        {
            "pyproject.toml": '[project]\nname = "svc"\n[project.scripts]\nsvc = "svc.cli:app"\n',
            "svc/api.py": """
            from fastapi import FastAPI
            from pydantic import BaseModel
            api = FastAPI()

            class Item(BaseModel):
                name: str

            @api.get("/items/{item_id}")
            def read(item_id: int): ...

            @api.post("/items")
            def create(item: Item): ...

            api.add_api_route("/health", lambda: "ok")
        """,
            "svc/cli.py": """
            import click, typer
            app = typer.Typer()

            @app.command()
            def sync(source: str, dry_run: bool = False): ...

            @click.command()
            @click.option("--verbose")
            def legacy(verbose): ...
        """,
            "svc/agent.py": """
            from mcp.server.fastmcp import FastMCP
            mcp = FastMCP("ops")

            @mcp.tool()
            def restart_pod(name: str) -> str: ...
        """,
            "function_app.py": """
            import azure.functions as func
            app = func.FunctionApp()

            @app.timer_trigger(schedule="0 */5 * * * *", arg_name="timer")
            def heartbeat(timer): ...

            @app.route(route="ping")
            def ping(req): ...
        """,
        }
    )
    kinds = sorted(c.kind for c in report.capabilities)
    assert kinds == sorted(
        [
            "script",
            "http-route",
            "http-route",
            "http-route",
            "http-route",
            "data-model",
            "cli-command",
            "cli-command",
            "cli-option",
            "cli-option",
            "cli-option",
            "agent-tool",
            "trigger",
        ]
    )
    assert report.mode == "app"
    assert report.capability_points == 9 + 0.25 * 4


def test_argparse_subcommands_and_options(run):
    report = run(
        {
            "tool.py": """
        import argparse
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers()
        sub.add_parser("build").add_argument("--target")
        sub.add_parser("clean")
        parser.add_argument("-h", "--help")

        if __name__ == "__main__":
            parser.parse_args()
    """
        }
    )
    assert sorted(c.kind for c in report.capabilities) == [
        "cli-command",
        "cli-command",
        "cli-option",
        "script",
    ]


def test_many_small_files_are_not_bloat(run):
    """Clean Code (ch. 10) prefers many small classes and files: no penalty for them."""
    files = {f"pkg/part{i}.py": f"def part{i}():\n    return {i}\n" for i in range(12)}
    files["pkg/cli.py"] = "from pkg import " + ", ".join(f"part{i}" for i in range(12)) + "\n"
    files["pkg/cli.py"] += (
        "if __name__ == '__main__':\n    print("
        + ", ".join(f"part{i}()" for i in range(12))
        + ")\n"
    )
    report = run(files)
    assert report.findings == []
    assert report.score == 0
    assert set(report.weights) == {"removable", "density"}


def test_every_finding_names_its_clean_code_heuristic():
    report = review(scan(EXAMPLES / "bloated_todo"))
    assert all(f.clean_code for f in report.findings)
    assert {f.clean_code for f in report.findings if f.rule == "duplicate-code"} == {
        "G5 Duplication"
    }


def test_unknown_functional_size_drops_density(run):
    report = run({"_internal.py": "def _f():\n    return 1\n\nprint(_f())\n"})
    assert "density" not in report.components
    assert any("functional size is unknown" in note for note in report.notes)


def test_score_combines_components_and_renormalises_weights(run):
    lines = "\n".join(f"    v{i} = {i}" for i in range(30))
    report = run(
        {"app.py": f"def unused():\n{lines}\n\nif __name__ == '__main__':\n    print(1)\n"}
    )
    # 31 of 33 SLOC removable -> removable saturates; density 33 SLOC / 1 point < baseline
    assert report.components == {"removable": 1.0, "density": 0.0}
    assert report.score == round(100 * 0.70 / 0.95, 1)
    assert (report.answer, report.verdict) == ("YES", "bloated")


def test_overlapping_findings_are_counted_once(run):
    report = run(
        {
            "app.py": """
        class Unused:
            def __init__(self, repo):
                self.repo = repo

            def get(self, key):
                return self.repo.get(key)

            def put(self, key, value):
                return self.repo.put(key, value)

        if __name__ == "__main__":
            print(1)
    """
        }
    )
    assert found(report) == {"Unused"}  # middle-man and dead-code on the same class
    assert len(report.findings) == 2
    assert report.removable_sloc == 7


def test_suppression_comment(run):
    report = run(
        {
            "app.py": """
        def kept():  # bloat: ignore
            return 1

        # bloat: ignore - called from a notebook
        def also_kept():
            return 2

        def reported():
            return 3

        if __name__ == "__main__":
            print(1)
    """
        }
    )
    assert found(report, "dead-code") == {"reported"}


def test_llm_opinion_is_averaged_into_density(run):
    seen = {}

    def judge(digest):
        seen["digest"] = digest
        return {
            "lean_sloc_estimate": 1,
            "model": "fake",
            "purpose": "",
            "assessment": "",
            "capabilities": [],
            "suspects": [],
        }

    report = run(
        {"README.md": "# Demo tool", "app.py": "if __name__ == '__main__':\n    print(1)\n"},
        judge=judge,
    )
    assert "# Demo tool" in seen["digest"]
    assert report.components["density"] == round((0 + 1 / 3) / 2, 3)  # 2 SLOC vs 1 lean -> 2x
    assert report.llm["model"] == "fake"


def test_llm_failure_becomes_a_note(run):
    from code_bloat_review.llm import LLMError

    def judge(digest):
        raise LLMError("quota exceeded")

    report = run({"app.py": "print(1)\n"}, judge=judge)
    assert report.llm is None
    assert "LLM opinion unavailable: quota exceeded" in report.notes
