from conftest import found

# ------------------------------------------------------------------ dead-code


def test_unreferenced_function_is_dead(run):
    report = run(
        {
            "app.py": """
        def used():
            return 1

        def unused():
            return 2

        print(used())
    """
        },
        mode="app",
    )
    assert found(report, "dead-code") == {"unused"}


def test_framework_hooks_are_kept_alive(run):
    report = run(
        {
            "app.py": """
        import threading
        from enum import Enum

        @app.get("/items")
        def list_items():
            return []

        class Worker(threading.Thread):
            def run(self):
                pass

        class Color(Enum):
            RED = 1

            @classmethod
            def _missing_(cls, value):
                return cls.RED

        class Plain:
            def __repr__(self):
                return "plain"

        print(Color, Plain)
    """
        },
        mode="app",
    )
    assert found(report, "dead-code") == set()


DUCK_TYPED = """
    import textwrap

    class TextWrapper(textwrap.TextWrapper):
        def _wrap_chunks(self, chunks):
            return chunks

    class Upper:
        def __init__(self, stream):
            self._stream = stream

        def write(self, text):
            return self._stream.write(text.upper())

        def flush(self):
            return self._stream.flush()

        def isatty(self):
            return self._stream.isatty()

    def main(req):
        return 200

    print(TextWrapper, Upper)
"""


def test_external_base_with_the_same_name_and_duck_typed_protocols(run):
    assert found(run({"app.py": DUCK_TYPED}, mode="app")) == set()


def test_names_in_config_and_strings_count_as_references(run):
    report = run(
        {
            "pyproject.toml": '[project]\nname = "x"\n[project.scripts]\nx = "pkg.cli:main"\n',
            "pkg/cli.py": """
            def main():
                return HANDLERS["go"]()

            def go():
                return 1

            HANDLERS = {"go": globals()["go"]}
        """,
        },
        mode="app",
    )
    assert found(report, "dead-code") == set()


def test_code_used_only_by_tests_is_dead_in_apps(run):
    report = run(
        {
            "app.py": """
            def helper():
                return 1

            if __name__ == "__main__":
                print("hi")
        """,
            "tests/test_app.py": "from app import helper\n\ndef test_helper():\n    assert helper() == 1\n",
        }
    )
    (finding,) = report.findings
    assert finding.symbol == "helper"
    assert "only from tests" in finding.message


def test_library_mode_treats_public_code_as_api(run):
    report = run(
        {
            "lib.py": """
        def public():
            return 1

        def _private():
            return 2
    """
        }
    )
    assert report.mode == "library"
    assert found(report, "dead-code") == {"_private"}


def test_methods_of_a_dead_class_are_not_reported_twice(run):
    report = run(
        {
            "app.py": """
        class Unused:
            def method(self):
                return 1
    """
        },
        mode="app",
    )
    assert found(report, "dead-code") == {"Unused"}


# ------------------------------------------------------- pass-through / override


def test_function_that_only_forwards_is_a_pass_through(run):
    report = run(
        {
            "app.py": """
        def fetch(url, *, timeout=5):
            return _fetch(url, timeout=timeout)

        def adds_value(url):
            return _fetch(url, timeout=10)

        def no_params():
            return _fetch()

        def chained(item):
            return REGISTRY.setdefault("k", []).append(item)

        @cached
        def decorated(url):
            return _fetch(url)

        def _fetch(*args, **kwargs):
            return args, kwargs

        print(fetch, adds_value, no_params, decorated, chained)
    """
        },
        mode="app",
    )
    assert found(report, "pass-through") == {"fetch"}


def test_public_aliases_in_a_library_are_api(run):
    source = """
        def unstyle(text):
            return _strip(text)

        def _alias(text):
            return _strip(text)

        def _strip(text):
            return text.strip()

        print(_alias)
    """
    assert found(run({"lib.py": source}), "pass-through") == {"_alias"}


def test_override_that_only_calls_super(run):
    report = run(
        {
            "app.py": """
        class Base:
            def __init__(self, x):
                self.x = x

        class Same(Base):
            def __init__(self, x):
                super().__init__(x)

        class Different(Base):
            def __init__(self, x):
                super().__init__(x * 2)

        print(Same(1), Different(1))
    """
        },
        mode="app",
    )
    assert found(report, "useless-override") == {"Same.__init__"}


def test_middle_man_class(run):
    report = run(
        {
            "app.py": """
        class Service:
            def __init__(self, repo):
                self.repo = repo

            def get(self, key):
                return self.repo.get(key)

            def put(self, key, value):
                return self.repo.put(key, value)

        class Busy:
            def __init__(self, repo):
                self.repo = repo

            def get(self, key):
                return self.repo.get(key)

            def total(self):
                return sum(self.repo.values())

            def report(self):
                return f"{self.total()} items"

        print(Service(None).get, Service(None).put, Busy(None).report)
    """
        },
        mode="app",
    )
    (finding,) = [f for f in report.findings if f.rule == "middle-man"]
    assert finding.symbol == "Service"
    assert finding.removable == 7  # the whole class can go


# ----------------------------------------------------------- abstractions


ABC_SOURCE = """
    from abc import ABC, abstractmethod

    class Store(ABC):
        @abstractmethod
        def load(self): ...

    class FileStore(Store):
        def load(self):
            return open("f").read()

    print(FileStore().load())
"""


def test_abstract_base_with_one_implementation(run):
    report = run({"app.py": ABC_SOURCE}, mode="app")
    assert found(report, "single-impl-abstraction") == {"Store"}


def test_abstraction_with_a_test_double_is_justified(run):
    report = run(
        {
            "app.py": ABC_SOURCE,
            "tests/test_app.py": "from app import Store\n\nclass FakeStore(Store):\n    def load(self):\n        return ''\n",
        },
        mode="app",
    )
    assert found(report, "single-impl-abstraction") == set()


def test_plugin_bases_are_extension_points(run):
    report = run({"app/plugins/base.py": ABC_SOURCE.replace("Store", "AuthPlugin")}, mode="app")
    assert found(report, "single-impl-abstraction") == set()


def test_protocols_and_null_objects_are_not_abstractions_to_inline(run):
    report = run(
        {
            "app.py": """
        from typing import Protocol

        class Store(Protocol):
            def load(self): ...

        class FileStore(Store):
            def load(self):
                return 1

        class NullLogger:
            def log(self, message):
                pass

        print(FileStore().load(), NullLogger().log)
    """
        },
        mode="app",
    )
    assert found(report, "single-impl-abstraction") == set()


def test_class_with_init_and_one_method(run):
    report = run(
        {
            "app.py": """
        from dataclasses import dataclass

        class Greeter:
            def __init__(self, name):
                self.name = name

            def greet(self):
                return f"hi {self.name}"

        class Counter:
            def __init__(self):
                self.n = 0

            def inc(self):
                self.n += 1

            def get(self):
                return self.n

        @dataclass
        class Point:
            x: int

            def norm(self):
                return abs(self.x)

        print(Greeter("a").greet(), Counter().inc, Counter().get, Point(1).norm())
    """
        },
        mode="app",
    )
    assert found(report, "trivial-class") == {"Greeter"}


# --------------------------------------------------------- small structures


STRATEGIES = """
    class OfflineSummarizer:
        def summarize(self, findings):
            return str(findings)

    class LLMSummarizer:
        def __init__(self, client):
            self.client = client

        def summarize(self, findings):
            return self.client.ask(findings)

    print(OfflineSummarizer, LLMSummarizer)
"""


def test_one_method_classes_that_are_interchangeable_strategies(run):
    assert found(run({"app.py": STRATEGIES}, mode="app"), "trivial-class") == set()


def test_try_that_only_reraises(run):
    report = run(
        {
            "app.py": """
        def a():
            try:
                return 1
            except ValueError:
                raise

        def b():
            try:
                return 1
            except ValueError as exc:
                raise exc

        def c():
            try:
                return 1
            except ValueError:
                raise
            except Exception:
                print("logged")
                raise

        def d():
            try:
                return 1
            except ValueError:
                raise
            finally:
                print("cleanup")

        print(a, b, c, d)
    """
        },
        mode="app",
    )
    assert [f.line for f in report.findings if f.rule == "useless-try"] == [2, 8]


def test_java_style_accessors(run):
    report = run(
        {
            "app.py": """
        class User:
            def __init__(self, name):
                self._name = name

            def get_name(self):
                return self._name

            def set_name(self, name):
                self._name = name

            def get_display(self):
                return self._name.title()

        u = User("x")
        print(u.get_name(), u.set_name, u.get_display())
    """
        },
        mode="app",
    )
    assert found(report, "trivial-accessor") == {"User.get_name", "User.set_name"}


def test_exception_classes_nobody_catches(run):
    report = run(
        {
            "app.py": """
        class NeverCaught(Exception):
            pass

        class Caught(Exception):
            pass

        class Mapped(Exception):
            pass

        class Rich(Exception):
            def __init__(self, code):
                self.code = code

        def f(x):
            if x == 1:
                raise NeverCaught()
            if x == 2:
                raise Caught("x")
            if x == 3:
                raise Mapped
            raise Rich(5)

        app.add_exception_handler(Mapped, lambda r, e: None)
        try:
            f(1)
        except Caught:
            pass
    """
        },
        mode="app",
    )
    assert found(report, "unused-exception") == {"NeverCaught"}


def test_unused_imports(run):
    report = run(
        {
            "pkg/__init__.py": "from .core import helper\n",
            "pkg/core.py": """
                from __future__ import annotations

                import os, sys
                import re
                import json as json
                import logging  # noqa: F401 - configures handlers on import
                from typing import TYPE_CHECKING, Any
                from collections import OrderedDict

                if TYPE_CHECKING:
                    from pathlib import Path

                def helper(path: "Path") -> Any:
                    return os.getcwd()

                def _f():
                    return OrderedDict
            """,
        },
        mode="app",
    )
    imports = {(f.symbol, f.removable) for f in report.findings if f.rule == "unused-import"}
    assert imports == {("sys", 0), ("re", 1)}  # only a fully unused statement can go
