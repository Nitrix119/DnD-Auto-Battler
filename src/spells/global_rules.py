"""Install core *global* rules as block-engine triggers (Phase 2.9, §4.7 step 3).

The global combat rules (``rules/global/*`` — damage resistance/immunity/
vulnerability, the nat-20/nat-1 crit rules) are event-modifier logic: they react to
an event and reach back onto it. Now that the event-modifier block family exists,
those rules can run on the **block engine** instead of the legacy rule engine's
``BUILTIN_EFFECTS`` dispatch — a permanent (lifetime-less) ``trigger`` per rule,
subscribed at combat start, whose ``then`` mutates the live event.

This is the first production repoint of §4.7 and deliberately the *small* one: it
touches only the **global** rules whose every effect is a pure event-modifier we
have a block for (``block_eligible``). Everything else — the entity-effect rules
reached via ``RuleEngine.apply_effect``, and the side-effecting globals
(``ForceConcentrationCheck``, ``RefillResources``) that fire *on* an event rather
than mutating it — stays on the legacy engine for now. The two paths are kept
separate: the caller installs the eligible rules here and disables exactly those on
the rule engine (``rule.enabled = False``), so nothing is applied twice.

Priority: global-rule triggers install at **priority 0** (matching the legacy rule
dispatch), relying on subscription order for the rest — none of these rules needs a
specific order relative to the others.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Set

from . import blocks as _blocks  # noqa: F401  (registers the block catalogue)
from .block import parse_program
from .context import CastEnv, Invocation, seed_context
from .fold import rule_to_trigger_blocks
from .runner import run_program

# The pure event-modifier actions — those whose block form mutates the live event
# and needs no holder/target. A global rule is block-eligible iff every one of its
# effects is one of these (so we can prove nothing forward-effecting is dropped).
_EVENT_MODIFIER_ACTIONS = frozenset(
    {
        "ModifyDamage",
        "ForceCriticalHit",
        "ForceCriticalMiss",
        "GrantAdvantage",
        "GrantDisadvantage",
        "Cancel",
    }
)


def block_eligible(rule: Any) -> bool:
    """True if *rule*'s every effect is a pure event-modifier with a block.

    Conservative by construction: a rule with any non-event-modifier effect (a
    forward side-effect such as ``ForceConcentrationCheck`` / ``RefillResources``,
    or an action we have no block for) stays on the legacy engine.
    """
    effects = getattr(rule, "effects", None) or []
    return bool(effects) and all(
        e.get("action") in _EVENT_MODIFIER_ACTIONS for e in effects
    )


def install_global_rules(
    rules: Iterable[Any],
    *,
    event_bus: Any,
    damage_processor: Optional[Any] = None,
) -> Set[str]:
    """Install the block-eligible *rules* as permanent block-engine triggers.

    Returns the set of rule names actually installed, so the caller can disable
    exactly those on the legacy rule engine (avoiding double application). A global
    rule has no caster/holder — its event-modifier effects reach the live event, not
    an entity — so the install invocation carries no caster/target.
    """
    handled: Set[str] = set()
    env = CastEnv(action=None, event_bus=event_bus, damage_processor=damage_processor)
    for rule in rules:
        if not block_eligible(rule):
            continue
        program = parse_program(rule_to_trigger_blocks(rule, priority=0))
        # A global rule has no caster/target — its event-modifier effects reach the
        # live event, not an entity — so pass None; the trigger never reads them.
        inv = Invocation(
            env=env,
            caster=None,  # type: ignore[arg-type]
            target=None,  # type: ignore[arg-type]
            context=seed_context(0),
        )
        run_program(program, inv)
        handled.add(rule.name)
    return handled
