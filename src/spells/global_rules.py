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
