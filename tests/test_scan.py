import subprocess

from conftest import write

from code_bloat_review.scan import is_test_path, scan


def test_python_sloc_skips_blanks_comments_and_docstrings(tmp_path):
    write(
        tmp_path,
        {
            "mod.py": '''
        """Module docstring
        spanning lines."""

        # a comment
        def f(x):
            """Docstring."""
            text = """not a docstring"""
            return x  # trailing comment counts as code
    '''
        },
    )
    (f,) = scan(tmp_path).files
    assert f.sloc == 3
    assert f.tree is not None


def test_c_style_block_comments(tmp_path):
    write(
        tmp_path,
        {
            "a.ts": """
        /* header
         * more header
         */
        // line comment
        export const a = 1; /* trailing */
        /* inline */ const b = 2;
    """
        },
    )
    (f,) = scan(tmp_path).files
    assert f.sloc == 2


def test_invalid_python_is_counted_and_noted(tmp_path):
    write(tmp_path, {"broken.py": "def f(:\n    pass\n"})
    project = scan(tmp_path)
    assert project.files[0].tree is None
    assert project.files[0].sloc == 2
    assert "not valid Python 3." in project.notes[0]


def test_test_files_are_recognised():
    assert is_test_path("tests/test_x.py")
    assert is_test_path("pkg/foo_test.go")
    assert is_test_path("web/src/App.test.tsx")
    assert is_test_path("src/test/java/FooTest.java")
    assert not is_test_path("src/contest.py")
    assert not is_test_path("src/app/latest.py")


def test_default_and_user_excludes(tmp_path):
    write(
        tmp_path,
        {
            "app.py": "x = 1\n",
            "node_modules/lib/index.js": "module.exports = 1;\n",
            "pkg/migrations/0001.py": "x = 1\n",
            "legacy/old.py": "x = 1\n",
            "static/app.min.js": "var a=1;\n",
            "examples/demo.py": "x = 1\n",
            "docs/conf.py": "x = 1\n",
        },
    )
    paths = {f.path for f in scan(tmp_path, exclude=["legacy/*"]).files}
    assert paths == {"app.py"}


def test_gitignore_is_honoured_in_git_repos(tmp_path):
    write(
        tmp_path, {"app.py": "x = 1\n", "generated/out.py": "y = 2\n", ".gitignore": "generated/\n"}
    )
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert {f.path for f in scan(tmp_path).files} == {"app.py"}


def test_readme_and_config_texts_are_kept(tmp_path):
    write(
        tmp_path, {"README.md": "# Hello", "pyproject.toml": "[project]\nname='x'\n", "app.py": ""}
    )
    project = scan(tmp_path)
    assert project.readme == "# Hello"
    assert "pyproject.toml" in project.texts
