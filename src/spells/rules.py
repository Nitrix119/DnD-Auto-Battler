"""Load rule JSON and install it on the block engine.

A rule is a block ``program`` of ``trigger`` blocks, so installing one is the block
engine's job — these functions are the seam between the rule *data* in
:mod:`src.rules` (``Rule``, ``RuleLoader``, ``EffectRegistry``) and the engine that
runs it. Two shapes:

- **Global** (:func:`install_rule`, :func:`load_rules_from_directory`) — a rule with
  no holder, whose triggers fire for the whole combat: the concentration check,
  damage resistance/immunity/vulnerability, the crit rules, the per-turn refill.
- **Entity-scoped** (:func:`apply_entity_rule`) — a rule held by one creature: a
  feature such as Colossus Slayer, or the mechanics behind a condition. Owned by a
  ``LifetimeScope`` on that entity, so a ``duration_rounds`` rule expires on the
  holder's turn and ``Entity.remove_effect`` tears it down by name.

This replaced ``rules.RuleEngine``, which had shrunk to a loader that reached into
this package to do the installing — an inverted dependency. ``src.rules`` is now pure
data with no engine in it.
"""

from __future__ import annotations

import os
from typing import Any, List, Optional

from src.rules.rule import Rule
from src.rules.rule_loader import RuleLoader

from .entity_effects import install_entity_effect
from .global_rules import install_global_rules


def install_rule(
    rule: Rule, *, event_bus: Any, damage_processor: Any = None
) -> None:
    """Install *rule* as permanent global triggers on the shared event bus."""
    install_global_rules(
        [rule], event_bus=event_bus, damage_processor=damage_processor
    )


def load_rule_file(
    path: str, *, event_bus: Any, damage_processor: Any = None
) -> Rule:
    """Load one JSON rule file and install it. Returns the loaded Rule."""
    rule = RuleLoader.load(path)
    install_rule(rule, event_bus=event_bus, damage_processor=damage_processor)
    return rule


def load_rules_from_directory(
    path: str, *, event_bus: Any, damage_processor: Any = None
) -> List[Rule]:
    """Recursively load and install every JSON rule under *path*."""
    rules: List[Rule] = []
    for dirpath, _dirs, filenames in os.walk(path):
        for filename in sorted(filenames):
            if filename.endswith(".json"):
                rules.append(load_rule_file(
                    os.path.join(dirpath, filename),
                    event_bus=event_bus, damage_processor=damage_processor,
                ))
    return rules


def apply_entity_rule(
    entity: Any,
    rule: Rule,
    *,
    event_bus: Any,
    damage_processor: Any = None,
    instance_fields: Optional[dict] = None,
) -> None:
    """Install *rule* on *entity* as holder-scoped block triggers.

    The rider's holder is *entity*, so its ``entity``/``event.caster`` resolves to it.
    Its triggers are owned by a lifetime scope keyed to ``rule.name``.

    Args:
        instance_fields: per-application values bound into the rider's trigger blocks
            as ``bindings`` (e.g. Charmed's ``charmer``).

    Raises:
        ValueError: if the rule has nothing to install (an empty program).
    """
    if not install_entity_effect(
        entity,
        rule,
        event_bus=event_bus,
        damage_processor=damage_processor,
        instance_fields=instance_fields,
    ):
        raise ValueError(
            f"Rule {rule.name!r} has an empty block program, so there is nothing "
            f"to install on {getattr(entity, 'name', entity)!r}."
        )
