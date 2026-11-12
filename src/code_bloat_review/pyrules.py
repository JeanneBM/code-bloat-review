"""Python analysis: a definition/reference index, the bloat rules and capability detection.

Rules are deliberately conservative: a false "this is bloat" costs more trust than a
missed one, so anything a framework might call (decorated code, subclasses of external
classes, dunder and hook methods) is left alone.
"""

from __future__ import annotations

import ast
import builtins
import re
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass

from .models import Capability, Finding, SourceFile
from .scan import docstring_nodes, line_of

# fmt: off
FUNCTION = (ast.FunctionDef, ast.AsyncFunctionDef)
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
BUILTIN_EXCEPTIONS = {
    name for name, value in vars(builtins).items()
    if isinstance(value, type) and issubclass(value, BaseException)
}

# Decorators that change *how* a definition is called, not *whether* something calls it.
NEUTRAL_DECORATORS = {
    "property", "setter", "getter", "deleter", "cached_property", "staticmethod",
    "classmethod", "abstractmethod", "override", "overload", "cache", "lru_cache",
    "dataclass", "total_ordering", "final", "define", "frozen", "mutable",
}
# Base classes that never call user methods behind the scenes (frameworks do).
NEUTRAL_BASES = {
    "object", "ABC", "Protocol", "Generic", "NamedTuple", "TypedDict",
    "Enum", "IntEnum", "StrEnum", "Flag", "IntFlag",
} | BUILTIN_EXCEPTIONS
# Methods of file-like objects: stdlib and third-party code call them through duck typing.
PROTOCOL_METHODS = {
    "read", "readline", "readlines", "write", "writelines", "flush", "close", "fileno",
    "isatty", "readable", "writable", "seekable", "seek", "tell", "truncate",
}
# Functions that runtimes and tools look up by name (Azure Functions v1, AWS Lambda, ...).
ENTRY_POINT_NAMES = {"main", "handler", "lambda_handler", "hook", "setup", "teardown"}
# Abstract bases in these places are extension points for third parties.
EXTENSION_HINTS = ("plugin", "extension", "hook")

ROUTE_DECORATORS = {"get", "post", "put", "patch", "delete", "head", "options", "route",
                    "api_route", "websocket"}
ROUTE_CALLS = {"add_url_rule", "add_api_route", "add_route"}
AGENT_TOOL_DECORATORS = {"tool", "function_tool", "kernel_function"}
TASK_DECORATORS = {"task", "shared_task", "periodic_task"}
MODEL_BASES = {"BaseModel", "SQLModel", "TypedDict", "NamedTuple", "Model", "DeclarativeBase",
               "Base", "Schema", "Struct"}
MODEL_DECORATORS = {"dataclass", "define", "frozen", "attrs"}
# fmt: on


def name_of(node: ast.AST | None) -> str:
    """Last identifier of a (possibly dotted, called or subscripted) expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return name_of(node.func)
    if isinstance(node, ast.Subscript):
        return name_of(node.value)
    return ""


@dataclass
class Definition:
    name: str
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    file: SourceFile
    owner: ast.ClassDef | None = None  # enclosing class, for methods

    @property
    def label(self) -> str:
        return f"{self.owner.name}.{self.name}" if self.owner else self.name

    @property
    def span(self) -> tuple[int, int]:
        start = min([self.node.lineno, *(d.lineno for d in self.node.decorator_list)])
        return start, self.node.end_lineno or self.node.lineno

    @property
    def private(self) -> bool:
        parts = self.file.path.split("/")
        return (
            self.name.startswith("_")
            or bool(self.owner and self.owner.name.startswith("_"))
            or any(p.startswith("_") and p not in ("__init__.py", "__main__.py") for p in parts)
        )

    def finding(self, rule: str, message: str, ranges=None) -> Finding:
        return Finding(
            rule,
            self.file.path,
            self.node.lineno,
            self.label,
            message,
            tuple(ranges or (self.span,)),
        )


class PyIndex:
    """Who defines what, and which names are used where, across all Python files."""

    def __init__(self, files: list[SourceFile], texts: dict[str, str]):
        self.files = [f for f in files if f.tree is not None]
        self.defs: list[Definition] = []
        self.classes: dict[str, list[Definition]] = defaultdict(list)
        self.subclasses: dict[str, list[Definition]] = defaultdict(list)
        self.prod_refs: set[str] = set()
        self.test_refs: set[str] = set()
        self.handled: set[str] = set()  # names used other than in `raise X` or as a base
        self.imports: set[str] = set()  # absolute module paths
        self._external: dict[int, bool] = {}
        for f in self.files:
            self._index_definitions(f)
            self._index_references(f)
        for text in texts.values():  # entry points, handlers named in config, templates
            self.prod_refs.update(IDENTIFIER.findall(text))

    def class_defs(self) -> list[Definition]:
        return [d for d in self.defs if isinstance(d.node, ast.ClassDef)]

    def has_external_base(self, cls: ast.ClassDef) -> bool:
        """True if an ancestor comes from outside the project (a framework may call into it)."""
        key = id(cls)
        if key not in self._external:
            self._external[key] = False  # guards against inheritance cycles
            self._external[key] = any(
                kw.arg == "metaclass" and name_of(kw.value) != "ABCMeta" for kw in cls.keywords
            ) or any(self._base_is_external(name_of(b), cls) for b in cls.bases)
        return self._external[key]

    def _base_is_external(self, name: str, cls: ast.ClassDef) -> bool:
        if name in NEUTRAL_BASES:
            return False
        local = [d for d in self.classes.get(name, []) if d.node is not cls]
        return not local or any(self.has_external_base(d.node) for d in local)

    def _index_definitions(self, f: SourceFile) -> None:
        for node in f.tree.body:
            if isinstance(node, FUNCTION):
                self.defs.append(Definition(node.name, node, f))
            elif isinstance(node, ast.ClassDef):
                cls = Definition(node.name, node, f)
                self.defs.append(cls)
                self.classes[node.name].append(cls)
                for base in node.bases:
                    self.subclasses[name_of(base)].append(cls)
                self.defs += [
                    Definition(m.name, m, f, owner=node)
                    for m in node.body
                    if isinstance(m, FUNCTION)
                ]

    def _index_references(self, f: SourceFile) -> None:
        refs = self.test_refs if f.is_test else self.prod_refs
        docstrings = {id(n) for n in docstring_nodes(f.tree)}
        raise_or_base = set()
        for node in ast.walk(f.tree):
            if isinstance(node, ast.Raise) and node.exc is not None:
                exc = node.exc
                raise_or_base.add(id(exc.func if isinstance(exc, ast.Call) else exc))
            elif isinstance(node, ast.ClassDef):
                raise_or_base.update(id(b) for b in node.bases)
        for node in ast.walk(f.tree):
            if isinstance(node, ast.Name | ast.Attribute) and not isinstance(node.ctx, ast.Store):
                name = node.id if isinstance(node, ast.Name) else node.attr
                refs.add(name)
                if id(node) not in raise_or_base:
                    self.handled.add(name)
            elif isinstance(node, ast.ImportFrom):
                refs.update(a.name for a in node.names)
                if node.level == 0 and node.module:
                    self.imports.add(node.module)
                    self.imports.update(f"{node.module}.{a.name}" for a in node.names)
            elif isinstance(node, ast.Import):
                self.imports.update(a.name for a in node.names)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in docstrings:
                    refs.update(IDENTIFIER.findall(node.value))


# --------------------------------------------------------------------------- rules


def dead_code(ix: PyIndex, mode: str) -> list[Finding]:
    found, dead_classes = [], set()
    for d in ix.defs:
        if d.file.is_test or (d.owner and id(d.owner) in dead_classes) or d.name in ix.prod_refs:
            continue
        in_tests = d.name in ix.test_refs
        if (in_tests and mode == "library") or _kept_alive(ix, d, mode):
            continue
        kind = "class" if isinstance(d.node, ast.ClassDef) else "method" if d.owner else "function"
        if kind == "class":
            dead_classes.add(id(d.node))
        usage = "referenced only from tests" if in_tests else "never referenced"
        found.append(d.finding("dead-code", f"{kind} is {usage}"))
    return found


def pass_through(ix: PyIndex, mode: str) -> list[Finding]:
    found = []
    for d in ix.defs:
        if d.file.is_test or isinstance(d.node, ast.ClassDef) or d.node.decorator_list:
            continue
        call = forwarded_call(d.node, method=d.owner is not None)
        if call is None:
            continue
        target = ast.unparse(call.func)
        func = call.func
        if (
            d.owner
            and isinstance(func, ast.Attribute)
            and func.attr == d.name
            and (isinstance(func.value, ast.Call) and name_of(func.value) == "super")
        ):
            found.append(
                d.finding("useless-override", f"only calls {target}() with the same arguments")
            )
        elif (
            d.owner is None
            and _parameters(d.node)
            and _is_reference(func)
            and (mode == "app" or d.private)  # a public alias in a library is API
        ):
            found.append(d.finding("pass-through", f"only forwards its arguments to {target}()"))
    return found


def middle_man(ix: PyIndex, mode: str) -> list[Finding]:
    found = []
    for cls in ix.class_defs():
        if cls.file.is_test or ix.has_external_base(cls.node):
            continue
        methods = [m for m in cls.node.body if isinstance(m, FUNCTION) and not _is_dunder(m.name)]
        delegates = defaultdict(list)
        for m in methods:
            plain = not m.decorator_list and m.name not in PROTOCOL_METHODS
            call = forwarded_call(m, method=True) if plain else None
            attr = (
                _self_attribute(call.func.value)
                if call and isinstance(call.func, ast.Attribute)
                else None
            )
            if attr:
                delegates[attr].append(m)
        if not delegates:
            continue
        attr, forwarding = max(delegates.items(), key=lambda item: len(item[1]))
        if len(forwarding) < 2 or len(forwarding) * 2 < len(methods):
            continue
        ranges = (
            [cls.span]
            if len(forwarding) == len(methods)
            else [(m.lineno, m.end_lineno or m.lineno) for m in forwarding]
        )
        message = (
            f"{len(forwarding)} of {len(methods)} methods only delegate to self.{attr}; "
            "callers could use it directly"
        )
        found.append(cls.finding("middle-man", message, ranges))
    return found


def single_implementation(ix: PyIndex, mode: str) -> list[Finding]:
    found = []
    for cls in ix.class_defs():
        node = cls.node
        if (
            cls.file.is_test
            or "Protocol" in _base_names(node)
            or (mode == "library" and not cls.private)
            or any(hint in f"{cls.file.path}/{cls.name}".lower() for hint in EXTENSION_HINTS)
        ):
            continue
        formal = _is_formal_abstract(node)
        if not formal and not _is_stub_interface(node):
            continue
        subclasses = ix.subclasses.get(cls.name, [])
        prod = [s.name for s in subclasses if not s.file.is_test]
        if len(prod) > 1 or len(prod) < len(subclasses) or not (prod or formal):
            continue  # several implementations, a test double, or a plain null object
        detail = f"a single implementation ({prod[0]})" if prod else "no implementation"
        found.append(
            cls.finding(
                "single-impl-abstraction", f"abstract base with {detail} and no test double"
            )
        )
    return found


def trivial_class(ix: PyIndex, mode: str) -> list[Finding]:
    found = []
    implementations = Counter(d.name for d in ix.defs if d.owner)
    for cls in ix.class_defs():
        node = cls.node
        if cls.file.is_test or node.decorator_list or node.keywords or cls.name in ix.subclasses:
            continue
        if any(name_of(b) != "object" for b in node.bases):
            continue
        body = _without_docstring(node.body)
        if len(body) != 2 or not all(
            isinstance(m, FUNCTION) and not m.decorator_list for m in body
        ):
            continue
        init, method = sorted(body, key=lambda m: m.name != "__init__")
        if init.name != "__init__" or _is_dunder(method.name) or implementations[method.name] > 1:
            continue  # several classes with this method: interchangeable strategies, keep them
        ranges = [(node.lineno, node.lineno), (init.lineno, init.end_lineno or init.lineno)]
        found.append(
            cls.finding(
                "trivial-class", f"only __init__ plus {method.name}(); a function would do", ranges
            )
        )
    return found


def useless_try(ix: PyIndex, mode: str) -> list[Finding]:
    found = []
    for f in ix.files:
        if f.is_test:
            continue
        for node in ast.walk(f.tree):
            if (
                isinstance(node, ast.Try | ast.TryStar)
                and node.handlers
                and not node.finalbody
                and not node.orelse
                and all(_only_reraises(h) for h in node.handlers)
            ):
                ranges = (
                    (node.lineno, node.lineno),
                    *((h.lineno, h.end_lineno or h.lineno) for h in node.handlers),
                )
                found.append(
                    Finding(
                        "useless-try",
                        f.path,
                        node.lineno,
                        "try",
                        "try/except only re-raises; drop the wrapper",
                        ranges,
                    )
                )
    return found


def unused_import(ix: PyIndex, mode: str) -> list[Finding]:
    """G12: imported names a module never uses (``__init__.py`` re-exports are API)."""
    found = []
    for f in ix.files:
        if f.is_test or f.path.rsplit("/", 1)[-1] == "__init__.py":
            continue
        used = _names_used_in(f)
        for node in ast.walk(f.tree):
            if (
                not isinstance(node, ast.Import | ast.ImportFrom)
                or "noqa" in f.lines[node.lineno - 1]
            ):
                continue
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            bound = [_bound_name(node, alias) for alias in node.names if alias.asname != alias.name]
            unused = [name for name in bound if name not in used and name != "*"]
            if unused:
                whole = len(unused) == len(node.names)
                ranges = [(node.lineno, node.end_lineno or node.lineno)] if whole else []
                found.append(
                    Finding(
                        "unused-import",
                        f.path,
                        node.lineno,
                        ", ".join(unused),
                        "imported but never used",
                        tuple(ranges),
                    )
                )
    return found


def trivial_accessor(ix: PyIndex, mode: str) -> list[Finding]:
    found = []
    for d in ix.defs:
        if d.file.is_test or d.owner is None or d.node.decorator_list:
            continue
        attr = _accessed_attribute(d)
        if attr:
            found.append(
                d.finding(
                    "trivial-accessor",
                    f"Java-style accessor for self.{attr}; "
                    "use the attribute (add a @property once logic appears)",
                )
            )
    return found


def unused_exception(ix: PyIndex, mode: str) -> list[Finding]:
    found = []
    for cls in ix.class_defs():
        name = cls.name
        if cls.file.is_test or name in ix.handled or (mode == "library" and not cls.private):
            continue
        if name not in ix.prod_refs and name not in ix.test_refs:
            continue  # never raised either: dead-code reports it
        bases = _base_names(cls.node)
        if not any(b in BUILTIN_EXCEPTIONS or b.endswith(("Error", "Exception")) for b in bases):
            continue
        if all(_is_stub_statement(s) for s in _without_docstring(cls.node.body)):
            found.append(
                cls.finding(
                    "unused-exception",
                    "never caught or checked by name; raising its base "
                    "or a built-in carries the same information",
                )
            )
    return found


RULES = (
    dead_code,
    pass_through,
    middle_man,
    single_implementation,
    trivial_class,
    useless_try,
    trivial_accessor,
    unused_exception,
    unused_import,
)


def python_findings(ix: PyIndex, mode: str) -> list[Finding]:
    return [finding for rule in RULES for finding in rule(ix, mode)]


# ---------------------------------------------------------------- capabilities


def python_capabilities(ix: PyIndex, texts: dict[str, str]) -> list[Capability]:
    """What the project offers its users: routes, commands, tools, triggers, models."""
    scripts = _console_scripts(texts)
    caps: list[Capability] = []
    for f in ix.files:
        if f.is_test:
            continue
        is_main_module = f.path.endswith("__main__.py")
        if is_main_module and not scripts:
            caps.append(Capability("script", f.path, f.path, 1))
        for node in ast.walk(f.tree):
            if isinstance(node, FUNCTION):
                caps += _decorator_capabilities(node, f)
            elif isinstance(node, ast.Call):
                caps += _call_capabilities(node, f)
            elif (
                isinstance(node, ast.If)
                and not (scripts or is_main_module)
                and _is_main_guard(node.test)
            ):
                caps.append(Capability("script", f.path, f.path, node.lineno))
    for cls in ix.class_defs():
        node = cls.node
        if not cls.file.is_test and (
            _base_names(node) & MODEL_BASES
            or any(name_of(d) in MODEL_DECORATORS for d in node.decorator_list)
        ):
            caps.append(Capability("data-model", cls.name, cls.file.path, node.lineno))
    return scripts + caps


def public_api(ix: PyIndex) -> list[Capability]:
    """For libraries, the public functions and methods are what the code does."""
    return [
        Capability("public-api", d.label, d.file.path, d.node.lineno)
        for d in ix.defs
        if not (
            d.file.is_test or isinstance(d.node, ast.ClassDef) or d.private or _is_dunder(d.name)
        )
    ]


def _console_scripts(texts: dict[str, str]) -> list[Capability]:
    caps = []
    for rel, text in texts.items():
        if rel.rsplit("/", 1)[-1] != "pyproject.toml":
            continue
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            continue
        project, poetry = data.get("project", {}), data.get("tool", {}).get("poetry", {})
        for name in [
            *project.get("scripts", {}),
            *project.get("gui-scripts", {}),
            *poetry.get("scripts", {}),
        ]:
            caps.append(Capability("script", name, rel, line_of(text, name)))
    return caps


def _decorator_capabilities(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, f: SourceFile
) -> list[Capability]:
    caps, options, is_command = [], 0, False
    for dec in fn.decorator_list:
        name = name_of(dec)
        if (
            name in ROUTE_DECORATORS
            and isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
        ):
            route = _route_path(dec)
            if route is not None:
                caps.append(Capability("http-route", f"{name.upper()} {route}", f.path, dec.lineno))
        elif name.endswith("_trigger"):  # Azure Functions: @app.timer_trigger(...), ...
            caps.append(Capability("trigger", f"{fn.name} ({name})", f.path, dec.lineno))
        elif name in AGENT_TOOL_DECORATORS:
            caps.append(Capability("agent-tool", fn.name, f.path, dec.lineno))
        elif name in TASK_DECORATORS:
            caps.append(Capability("task", fn.name, f.path, dec.lineno))
        elif name == "command":
            caps.append(Capability("cli-command", fn.name, f.path, dec.lineno))
            is_command = True
        elif name in ("option", "argument"):
            options += 1
    if is_command and not options:  # typer: the parameters are the options
        options = len(_parameters(fn))
    caps += [
        Capability("cli-option", f"{fn.name} #{i}", f.path, fn.lineno)
        for i in range(1, options + 1)
    ]
    return caps


def _call_capabilities(call: ast.Call, f: SourceFile) -> list[Capability]:
    name = name_of(call.func)
    arg = call.args[0] if call.args else None
    first = arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None
    if first is None:
        return []
    kind = None
    if isinstance(call.func, ast.Attribute):
        if name == "add_parser":
            kind = "cli-command"
        elif name == "add_argument" and first not in ("-h", "--help"):
            kind = "cli-option"
        elif name in ROUTE_CALLS:
            kind = "http-route"
    elif name in ("path", "re_path") and f.path.endswith("urls.py"):  # Django
        kind = "http-route"
    return [Capability(kind, first, f.path, call.lineno)] if kind else []


# --------------------------------------------------------------------- helpers


def forwarded_call(fn: ast.FunctionDef | ast.AsyncFunctionDef, method: bool) -> ast.Call | None:
    """The call ``fn`` consists of, if it passes on exactly ``fn``'s own parameters."""
    body = _without_docstring(fn.body)
    if len(body) != 1 or not isinstance(body[0], ast.Return | ast.Expr):
        return None
    value = body[0].value
    if isinstance(value, ast.Await):
        value = value.value
    if not isinstance(value, ast.Call):
        return None
    passed = []
    for arg in value.args:
        if isinstance(arg, ast.Starred) and isinstance(arg.value, ast.Name):
            passed.append("*" + arg.value.id)
        elif isinstance(arg, ast.Name):
            passed.append(arg.id)
        else:
            return None
    for kw in value.keywords:
        if not isinstance(kw.value, ast.Name) or kw.arg not in (None, kw.value.id):
            return None
        passed.append("**" + kw.value.id if kw.arg is None else kw.arg)
    return value if sorted(passed) == sorted(_parameters(fn, method)) else None


def _parameters(fn: ast.FunctionDef | ast.AsyncFunctionDef, method: bool = False) -> list[str]:
    args = fn.args
    names = [p.arg for p in [*args.posonlyargs, *args.args]][1 if method else 0 :]
    names += [p.arg for p in args.kwonlyargs]
    if args.vararg:
        names.append("*" + args.vararg.arg)
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return names


def _kept_alive(ix: PyIndex, d: Definition, mode: str) -> bool:
    """Definitions that something outside our sight (framework, user, protocol) may call."""
    name = d.name
    if (name.startswith("_") and name.endswith("_")) or name.startswith(("visit_", "pytest_")):
        return True  # dunder, sunder (_missing_) and visitor/plugin hooks
    if name in (PROTOCOL_METHODS if d.owner else ENTRY_POINT_NAMES):
        return True
    if not _plain(d.node.decorator_list):
        return True
    if d.owner and (ix.has_external_base(d.owner) or not _plain(d.owner.decorator_list)):
        return True
    if isinstance(d.node, ast.ClassDef) and ix.has_external_base(d.node):
        return True
    return mode == "library" and not d.private


def _plain(decorators: list[ast.expr]) -> bool:
    return all(name_of(d) in NEUTRAL_DECORATORS for d in decorators)


def _accessed_attribute(d: Definition) -> str | None:
    body = _without_docstring(d.node.body)
    prefix, field = d.name[:4], d.name[4:]
    params = _parameters(d.node, method=True)
    if len(body) != 1 or prefix not in ("get_", "set_") or not field:
        return None
    stmt, target = body[0], None
    if prefix == "get_" and not params and isinstance(stmt, ast.Return):
        target = stmt.value
    elif (
        prefix == "set_"
        and len(params) == 1
        and isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.value, ast.Name)
        and stmt.value.id == params[0]
    ):
        target = stmt.targets[0]
    attr = _self_attribute(target)
    return attr if attr in (field, "_" + field) else None


def _is_reference(node: ast.expr) -> bool:
    """``name`` or ``a.b.c``, i.e. a call target with no logic of its own."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name)


def _bound_name(node: ast.Import | ast.ImportFrom, alias: ast.alias) -> str:
    if alias.asname:
        return alias.asname
    return alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name


def _names_used_in(f: SourceFile) -> set[str]:
    """Names a module loads, plus identifiers in its strings (string annotations, __all__)."""
    docstrings = {id(n) for n in docstring_nodes(f.tree)}
    used = set()
    for node in ast.walk(f.tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store):
            used.add(node.id)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            used.update(IDENTIFIER.findall(node.value))
    return used


def _self_attribute(node: ast.AST | None) -> str | None:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    ):
        return node.attr
    return None


def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    first = body[0] if body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return body[1:]
    return body


def _is_stub_statement(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return stmt.value.value is Ellipsis
    return isinstance(stmt, ast.Raise) and name_of(stmt.exc) == "NotImplementedError"


def _is_stub_interface(node: ast.ClassDef) -> bool:
    methods = [m for m in node.body if isinstance(m, FUNCTION) and not _is_dunder(m.name)]
    return bool(methods) and all(
        all(_is_stub_statement(s) for s in _without_docstring(m.body)) for m in methods
    )


def _is_formal_abstract(node: ast.ClassDef) -> bool:
    if "ABC" in _base_names(node):
        return True
    if any(kw.arg == "metaclass" and name_of(kw.value) == "ABCMeta" for kw in node.keywords):
        return True
    return any(
        name_of(dec) == "abstractmethod"
        for m in node.body
        if isinstance(m, FUNCTION)
        for dec in m.decorator_list
    )


def _only_reraises(handler: ast.ExceptHandler) -> bool:
    if len(handler.body) != 1 or not isinstance(handler.body[0], ast.Raise):
        return False
    raise_ = handler.body[0]
    if raise_.cause is not None:
        return False
    return raise_.exc is None or (
        isinstance(raise_.exc, ast.Name) and raise_.exc.id == handler.name
    )


def _route_path(call: ast.Call) -> str | None:
    for arg in [
        *call.args[:1],
        *(k.value for k in call.keywords if k.arg in ("path", "route", "rule")),
    ]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def _is_main_guard(test: ast.expr) -> bool:
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def _base_names(node: ast.ClassDef) -> set[str]:
    return {name_of(b) for b in node.bases}


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")
