from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, Optional

from .rule import Rule


@dataclass
class EffectInstance:
    """A single application of a Rule to one entity.

    Wraps the shared Rule template with per-application data so that the same
    rule definition can be applied multiple times (to different entities, or
    multiple times to the same entity) with independent state.

    Attributes:
        rule: The shared Rule template defining triggers, condition, and effects.
        instance_fields: Arbitrary key/value data decided at apply time.  These
            become available in rule expressions as ``instance_fields.<key>``.
            Typical uses: ``charmer`` (the entity that applied charm),
            ``caster`` (spellcaster), ``damage_type`` (for typed resistances).
        duration_remaining: Per-application countdown copied from
            ``rule.duration_rounds`` at creation.  Ticked independently so that
            applying the same rule to two entities does not cause them to share
            a duration counter.
    """

    rule: Rule
    instance_fields: Dict[str, Any] = field(default_factory=dict)
    duration_remaining: Optional[int] = None

    def __post_init__(self) -> None:
        # Copy duration from the rule template so each application is independent.
        if self.duration_remaining is None:
            self.duration_remaining = self.rule.duration_rounds

    # Proxy frequently-used Rule attributes so callers can treat an
    # EffectInstance interchangeably with a Rule for name lookups.

    @property
    def name(self) -> str:
        return self.rule.name

    @property
    def enabled(self) -> bool:
        return self.rule.enabled

    def fields_namespace(self) -> SimpleNamespace:
        """Return instance_fields as a SimpleNamespace for expression access."""
        return SimpleNamespace(**self.instance_fields)
