"""Install *global* rules as block-engine triggers.

The global combat rules (``rules/global/*`` — damage resistance/immunity/
vulnerability, the nat-20/nat-1 crit rules, the concentration check, the per-turn
resource refill) have no holder: they apply to the whole combat. Each installs as a
permanent (lifetime-less) ``trigger`` per rule, subscribed at combat start, whose
``then`` either mutates the live event (the event-modifier family) or fires *on* it
to act on an entity (``force_concentration_check``, ``refill_resources``).

The entity-scoped sibling — a rule held by one creature — is
:func:`src.spells.entity_effects.install_entity_effect`.

Priority: global-rule triggers install at **priority 0**, relying on subscription
order for the rest — none of these rules needs a specific order relative to the
others.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Set

from . import blocks as _blocks  # noqa: F401  (registers the block catalogue)
from .block import parse_program
from .context import CastEnv, Invocation, seed_context
from .runner import run_program


def block_eligible(rule: Any) -> bool:
    """True if *rule* can run as a global trigger on the block engine.

    A rule is eligible iff it is **native** — it carries a block ``program`` (its
    behaviour is authored as trigger blocks directly). Every shipped global rule is
    native (Phase 3 §5); a non-native rule is not installed here.
    """
    return getattr(rule, "program", None) is not None


def install_global_rules(
    rules: Iterable[Any],
    *,
    event_bus: Any,
    damage_processor: Optional[Any] = None,
) -> Set[str]:
    """Install the native *rules* as permanent block-engine triggers.

    Returns the set of rule names actually installed. A global rule has no
    caster/holder — its event-modifier effects reach the live event, not an entity —
    so the install invocation carries no caster/target.
    """
    handled: Set[str] = set()
    env = CastEnv(action=None, event_bus=event_bus, damage_processor=damage_processor)
    for rule in rules:
        if rule.program is None:
            continue  # only native rules install on the block engine
        program = parse_program(rule.program)
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
