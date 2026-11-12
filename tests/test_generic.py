from conftest import found

BLOCK = """
    def {name}(rows):
        total = 0
        for row in rows:
            if row.active:
                total += row.amount * row.rate
                total -= row.discount
        return round(total, 2)
"""


def test_duplicated_block_across_files(run):
    report = run({"a.py": BLOCK.format(name="first"), "b.py": BLOCK.format(name="second")})
    (dup,) = [f for f in report.findings if f.rule == "duplicate-code"]
    assert dup.path == "b.py"
    assert dup.message == "repeats a.py:2"
    assert dup.removable == 6


def test_short_or_trivial_repeats_are_not_duplication(run):
    short = "def f(x):\n    y = x + 1\n    z = y * 2\n    return z\n"
    closers = "}\n});\n]\n)\n}\n});\n  }\n"  # identical, but carries no logic
    report = run(
        {
            "a.py": short,
            "b.py": short.replace("f(", "g("),
            "a.js": f"first();\n{closers}last();\n",
            "b.js": f"one();\n{closers}two();\n",
        }
    )
    assert found(report, "duplicate-code") == set()


SIGNATURE = """
    def {name}(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        tb: TracebackType | None,
        extra: int = 0,
    ) -> None:
        self.close()
"""


def test_repeated_multiline_signatures_are_not_duplication(run):
    report = run({"a.py": SIGNATURE.format(name="close"), "b.py": SIGNATURE.format(name="close")})
    assert found(report, "duplicate-code") == set()


def test_duplication_inside_tests_is_ignored(run):
    report = run(
        {"tests/test_a.py": BLOCK.format(name="t1"), "tests/test_b.py": BLOCK.format(name="t2")}
    )
    assert found(report, "duplicate-code") == set()


def test_unused_python_dependencies(run):
    report = run(
        {
            "pyproject.toml": """
            [project]
            name = "svc"
            dependencies = ["requests>=2", "PyYAML", "uvicorn[standard]", "azure-identity",
                            "python-dateutil", "pandas==2.2", "boto3"]
        """,
            "app.py": """
            import requests, yaml
            from azure.identity import DefaultAzureCredential
            from dateutil import parser
        """,
            "Dockerfile": "RUN pip install .\nCMD boto3-cli run\n",
        }
    )
    assert found(report, "unused-dependency") == {"pandas"}
    assert report.components["unused_deps"] == round((1 / 7) / 0.5, 3)


def test_requirements_txt(run):
    report = run(
        {"requirements.txt": "flask==3.0  # web\n-r dev.txt\nnumpy\n", "app.py": "import flask\n"}
    )
    assert found(report, "unused-dependency") == {"numpy"}


def test_lockfiles_are_skipped_in_favour_of_requirements_in(run):
    lock = "anyio==4.1 \\\n    --hash=sha256:abc\n    # via httpx\nhttpx==0.27\n"
    report = run(
        {"requirements.txt": lock, "requirements.in": "httpx\nrich\n", "app.py": "import httpx\n"}
    )
    assert found(report, "unused-dependency") == {"rich"}


def test_unused_js_dependencies(run):
    report = run(
        {
            "package.json": """
            {"dependencies": {"express": "^4", "lodash": "^4", "tailwindcss": "^4",
                              "react-dom": "^18", "next": "^14"},
             "scripts": {"dev": "next dev"}, "bin": {"svc": "bin/svc.js"}}
        """,
            "src/server.js": "const express = require('express');\nconst app = express();\n"
            "app.get('/health', (req, res) => res.send('ok'));\n",
            "src/client.tsx": "import { createRoot } from 'react-dom/client';\n",
            "src/index.css": '@import "tailwindcss";\n',
        }
    )
    assert found(report, "unused-dependency") == {"lodash"}
    assert {(c.kind, c.path) for c in report.capabilities} == {
        ("http-route", "src/server.js"),
        ("script", "package.json"),
    }


def test_routes_in_other_languages(run):
    report = run(
        {
            "main.go": 'func main() {\n\thttp.HandleFunc("/a", a)\n\tr.GET("/b", b)\n}\n',
            "Ctrl.java": 'class C {\n  @GetMapping("/x")\n  String x() { return ""; }\n}\n',
        }
    )
    assert sorted(c.kind for c in report.capabilities) == ["http-route"] * 3
    assert any("Structural rules cover Python" in n for n in report.notes)


COMMENTS = """
# Configuration helpers.
# Example
# type: ignore[attr-defined]
# TODO: call refresh(cache) once the API is stable
def load():
    return 1


# def old_load(path):
#     with open(path) as handle:
#         return handle.read()

# result = load()

# print(result)  -- a bare call alone could be prose
"""


def test_commented_out_python_code(run):
    report = run(
        {
            "app.py": COMMENTS,
            "web.ts": "// legacy:\n// const a = compute(x);\n// render(a);\nexport const b = 1;\n// see the docs for details\n",
        }
    )
    blocks = {
        (f.path, f.symbol, f.removable) for f in report.findings if f.rule == "commented-out-code"
    }
    assert blocks == {
        ("app.py", "lines 9-11", 3),
        ("app.py", "lines 13-13", 1),
        ("web.ts", "lines 2-3", 2),
    }
    assert {f.clean_code for f in report.findings if f.rule == "commented-out-code"} == {
        "C5 Commented-Out Code"
    }


def test_pseudo_code_inside_an_explanation_is_not_commented_out_code(run):
    source = "def f():\n    # after the loop the situation is:\n    #\n    #   left = items[:i]\n    #   rest = items[i:]\n    #   and nothing else changed\n    return 1\n"
    assert found(run({"app.py": source}), "commented-out-code") == set()
