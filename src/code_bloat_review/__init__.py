"""code-bloat-review: is this code disproportionately large for what it does?"""

from .report import render
from .review import review
from .scan import scan

__all__ = ["render", "review", "scan"]
__version__ = "0.1.0"
