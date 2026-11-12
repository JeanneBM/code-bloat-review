"""The yardstick: every rule enforces a heuristic from Robert C. Martin's *Clean Code* (2008).

"Lean" here means what Clean Code asks for, not the fewest characters: small functions,
small classes and many small files are fine (chapters 3 and 10), so the score never
penalises them. What counts as excess is code those heuristics say should not exist:
duplication, dead or commented-out code, clutter and ceremony that adds classes and
methods without adding behaviour (chapter 12, Simple Design rule 4).

Readability heuristics that say nothing about size (F1 Too Many Arguments, G25 Magic
Numbers, N1 Descriptive Names, ...) are deliberately not part of the score.
"""

SIMPLE_DESIGN = "Ch.12 Simple Design #4"

# rule -> (Clean Code reference, what the finding means)
RULES = {
    "duplicate-code": ("G5 Duplication", "block repeated elsewhere in the project"),
    "dead-code": (
        "F4 Dead Function / G9 Dead Code",
        "defined but never referenced (or only from tests)",
    ),
    "commented-out-code": (
        "C5 Commented-Out Code",
        "code kept in comments; version control remembers it",
    ),
    "unused-import": ("G12 Clutter", "imported name never used"),
    "unused-dependency": ("G12 Clutter", "declared dependency nobody imports or invokes"),
    "useless-override": ("G12 Clutter", "method that only calls super() with the same arguments"),
    "pass-through": ("G12 Clutter", "function that only forwards its arguments elsewhere"),
    "useless-try": ("G12 Clutter", "try/except that only re-raises"),
    "middle-man": (SIMPLE_DESIGN, "class whose methods mostly delegate to one attribute"),
    "single-impl-abstraction": (
        SIMPLE_DESIGN,
        "abstract base with one implementation and no test double",
    ),
    "trivial-class": (SIMPLE_DESIGN, "__init__ plus one method: a function would do"),
    "trivial-accessor": ("Ch.6 Data Abstraction", "get_x/set_x around a plain attribute"),
    "unused-exception": (
        "Ch.7 Exceptions by caller's needs",
        "custom exception nobody catches by name",
    ),
}


def reference(rule: str) -> str:
    return RULES.get(rule, ("", ""))[0]


def meaning(rule: str) -> str:
    return RULES.get(rule, ("", ""))[1]
