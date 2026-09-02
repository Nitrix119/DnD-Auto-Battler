"""Rule engine — loads JSON rule files and installs them on the block engine.

A rule is authored as a native block ``program``: its reactive behaviour lives in
``trigger`` blocks that subscribe to combat events. This class is the *loader seam* —
it reads the rule JSON (``rules/global/*``, ``rules/entity_effects/**``) and installs
each rule on the block engine, which is the single resolution path shared by rules,
spells and weapon attacks. It does not dispatch anything itself.

Two install shapes:

- **Global** (``load_rule`` / ``load_from_file`` / ``load_from_directory``) — a rule
  with no holder, whose triggers fire for the whole combat: the concentration check,
  damage resistance/immunity/vulnerability, the crit rules. Installed through
  :func:`src.spells.global_rules.install_global_rules`.
- **Entity-scoped** (``apply_effect``) — a rule held by one creature: a feature such
  as Colossus Slayer, or the mechanics behind a condition. Installed through
  :func:`src.spells.entity_effects.install_entity_effect` and owned by a
  ``LifetimeScope`` on that entity, so ``remove_effect`` tears it down and a
  ``duration_rounds`` rule expires on the holder's turn.

Expressions inside a rule's blocks are evaluated by :mod:`src.rules.expressions` under
an AST whitelist; the block evaluator drives them, not this class.
"""

import logging
import os
from typing import List, Optional

from src.combat.event_bus import EventBus
from .rule import Rule
from .rule_loader import RuleLoader

logger = logging.getLogger(__name__)


class RuleEngine:
    """Loads JSON-defined rules and installs them on the block engine.

    Usage::

        engine = RuleEngine(combat.event_bus, damage_processor=processor)
        engine.load_from_directory("rules/global")
    """

    def __init__(self, event_bus: EventBus,
                 damage_processor=None,
                 effect_registry=None) -> None:
        self.event_bus = event_bus
        self._damage_processor = damage_processor
        # The scanned rule catalogue (rules/entity_effects/**). Read by the
        # ``apply_condition`` block to find a condition's reactive rule by name, and
        # by SpellResolver; this engine carries it, it does not dispatch from it.
        self.effect_registry = effect_registry
        # Rules installed on the block engine by this loader, kept for inspection.
        self._native_rules: List[Rule] = []

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_rule(self, rule: Rule) -> None:
        """Install *rule* as permanent global triggers on the shared event bus.

        Args:
            rule: A Rule instance (e.g. from RuleLoader).
        """
        # Lazy import avoids the rules -> spells -> combat import cycle (mirrors
        # apply_effect). ``install_global_rules`` installs the rule's trigger blocks
        # with this engine's damage_processor (None is fine — no global rule rolls
        # damage).
        from src.spells.global_rules import install_global_rules

        install_global_rules(
            [rule], event_bus=self.event_bus,
            damage_processor=self._damage_processor,
        )
        self._native_rules.append(rule)

    def load_from_directory(self, path: str) -> List[Rule]:
        """Recursively load and install all JSON rule files under a directory.

        Args:
            path: Path to the directory to search.

        Returns:
            List of loaded Rules.
        """
        rules = []
        for dirpath, _, filenames in os.walk(path):
            for filename in filenames:
                if filename.endswith(".json"):
                    rules.append(self.load_from_file(os.path.join(dirpath, filename)))
        return rules

    def load_from_file(self, path: str) -> Rule:
        """Load a JSON rule file and install it.

        Args:
            path: Path to the JSON rule file.

        Returns:
            The loaded Rule (for inspection).
        """
        rule = RuleLoader.load(path)
        self.load_rule(rule)
        return rule

    # ------------------------------------------------------------------
    # Entity-scoped effects
    # ------------------------------------------------------------------

    def apply_effect(self, entity, rule: Rule,
                     instance_fields: Optional[dict] = None) -> None:
        """Install *rule* on *entity* as holder-scoped block triggers.

        The rider's holder is *entity*, so its ``entity``/``event.caster`` resolves to
        it. The triggers are owned by a lifetime scope keyed to ``rule.name``, so a
        ``duration_rounds`` rule expires on the holder's turn and ``remove_effect``
        disposes it by name.

        Args:
            entity: The entity to apply the effect to.
            rule: The Rule template to attach.
            instance_fields: Optional per-application data, bound into the rider's
                trigger blocks as ``bindings`` (e.g. Charmed's ``charmer``).

        Raises:
            ValueError: If the rule has nothing to install (an empty program).
        """
        # Imported lazily to avoid a rules -> spells -> combat import cycle.
        from src.spells.entity_effects import install_entity_effect

        if not install_entity_effect(
            entity,
            rule,
            event_bus=self.event_bus,
            damage_processor=self._damage_processor,
            instance_fields=instance_fields,
        ):
            raise ValueError(
                f"Rule {rule.name!r} has an empty block program, so there is "
                f"nothing to install on {getattr(entity, 'name', entity)!r}."
            )

    def remove_effect(self, entity, name: str) -> None:
        """Remove a named effect from an entity."""
        entity.remove_effect(name)
