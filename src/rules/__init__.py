"""Rules package — JSON-driven declarative rule system."""

from .rule import Rule
from .rule_engine import RuleEngine
from .rule_loader import RuleLoader
from .effects import BUILTIN_EFFECTS

__all__ = [
    "Rule",
    "RuleEngine",
    "RuleLoader",
    "BUILTIN_EFFECTS",
]
