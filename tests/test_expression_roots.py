"""The declared expression roots must match the namespace expressions really run in.

`EXPRESSION_ROOTS` is what the validator checks an expression's top-level names
against. If it drifts from what `eval_context` actually builds, the validator either
rejects a name that works (blocking authors) or accepts one that is a NameError at
run time — swallowed inside a trigger guard as "did not fire", which is the failure
mode this whole gate exists to prevent.

So this checks the declaration against a real invocation rather than trusting it.
"""

from src.models import AbilityScores, StatBlock, Entity
from src.combat.event_bus import EventBus
from src.spells.context import (
    CONTEXT_KEYS,
    EXPRESSION_ROOTS,
    CastEnv,
    Invocation,
    eval_context,
    seed_context,
)


def _invocation(**kwargs) -> Invocation:
    sb = StatBlock(
        name="Caster", ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=20, armor_class=10,
    )
    entity = Entity(sb)
    env = CastEnv(action=None, event_bus=EventBus(), damage_processor=None)
    return Invocation(
        env=env, caster=entity, target=entity, context=seed_context(0), **kwargs
    )


def test_declared_roots_match_eval_context():
    """The list is a declaration; this is the check that it is true."""
    actual = set(eval_context(_invocation()))
    assert actual == set(EXPRESSION_ROOTS), (
        "EXPRESSION_ROOTS has drifted from eval_context: "
        f"missing from the declaration {sorted(actual - set(EXPRESSION_ROOTS))}, "
        f"declared but absent {sorted(set(EXPRESSION_ROOTS) - actual)}"
    )


def test_roots_hold_for_a_fired_trigger_too():
    """A trigger fires with the event's data merged in — same top-level names."""
    inv = _invocation(event_data={"attacker": None, "total": 7})
    assert set(eval_context(inv)) == set(EXPRESSION_ROOTS)


def test_context_keys_match_the_seeder():
    """The sibling declaration: `context.X` names come from seed_context itself."""
    assert set(CONTEXT_KEYS) == set(seed_context(0))


def test_every_root_is_actually_usable_in_an_expression():
    """A declared root that raises when referenced would be a lie."""
    from src.rules.expressions import evaluate

    ctx = eval_context(_invocation())
    for root in EXPRESSION_ROOTS:
        evaluate(root, ctx)  # must not raise
