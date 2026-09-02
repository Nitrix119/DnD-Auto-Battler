"""Rules package — the rule *data* layer.

A rule is a block ``program``; this package defines it (:class:`Rule`), loads it from
JSON (:class:`RuleLoader`), indexes a catalogue of them (:class:`EffectRegistry`), and
provides the sandboxed expression evaluator its blocks use. **Installing** a rule is
the block engine's job — see :mod:`src.spells.rules`.
"""

from .effect_registry import EffectRegistry
from .rule import Rule
from .rule_loader import RuleLoader

__all__ = [
    "EffectRegistry",
    "Rule",
    "RuleLoader",
]
