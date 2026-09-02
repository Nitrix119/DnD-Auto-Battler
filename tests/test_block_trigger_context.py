"""The firing context a block ``trigger`` builds — crit seeding + dynamic types.

Two general affordances the Colossus Slayer migration (Phase 3 §2) relies on, tested
in isolation so they are pinned independently of that spell:

1. **Crit seed.** A ``trigger`` firing on an event carrying ``critical_hit`` seeds it
   into the fresh invocation context, so a ``damage`` block in the ``then`` body
   doubles on a crit exactly as a mid-cast damage block does (5e RAW: on-hit bonus
   dice double on a critical hit). No flag → no doubling.
2. **Dynamic damage type.** A ``damage`` block's ``damage_type`` may be an expression
   resolved at run time (``event.action.primary_damage_type``), not only a literal
   enum name — so an on-hit rider can deal *the weapon's own type*.
"""

from src.models import AbilityScores, StatBlock, Entity, AttackAction, Damage, DamageType
from src.combat.event_bus import EventBus
from src.combat.damage_processor import DamageProcessor
from src.combat.events import EventType
from src.combat.event_data import AttackHitData

import src.spells.blocks  # noqa: F401  (registers the block catalogue)
from src.spells.block import parse_program
from src.spells.context import CastEnv, Invocation, seed_context
from src.spells.runner import run_program


def _entity(name="E", hp=40, ac=10):
    sb = StatBlock(
        name=name, ability_scores=AbilityScores(10, 10, 10, 10, 10, 10),
        hit_points_max=hp, armor_class=ac,
    )
    return Entity(sb)


def _install(bus, dp, holder, program):
    """Run a program once so its ``trigger`` blocks subscribe to *bus*."""
    env = CastEnv(action=None, event_bus=bus, damage_processor=dp)
    inv = Invocation(env=env, caster=holder, target=holder, context=seed_context(0))
    run_program(parse_program(program), inv)


# A rider that deals a flat "2d1" (deterministic: 2) on any ATTACK_HIT to the
# event's defender. On a crit the damage block doubles the dice → "4d1" = 4.
_ONHIT_DAMAGE = [{
    "block": "trigger", "event": "ATTACK_HIT", "holder": "caster",
    "target": "event.defender",
    "then": [{"block": "damage", 
              "damage_type": "FIRE", "formula": "2d1"}],
}]


class TestCritSeed:

    def _run(self, *, critical_hit):
        bus = EventBus()
        dp = DamageProcessor(bus)
        attacker = _entity("A")
        target = _entity("T", hp=40)
        _install(bus, dp, attacker, _ONHIT_DAMAGE)
        before = target.hp
        bus.emit(
            EventType.ATTACK_HIT,
            AttackHitData(attacker=attacker, defender=target, action=None,
                          roll=25, critical_hit=critical_hit),
        )
        return before - target.hp

    def test_no_crit_deals_base_dice(self):
        assert self._run(critical_hit=False) == 2

    def test_crit_doubles_the_dice(self):
        assert self._run(critical_hit=True) == 4


class TestDynamicDamageType:

    def test_damage_type_expression_resolves_the_weapons_type(self):
        """A ``damage_type`` expression resolves against the firing event — here to
        the attacking weapon's own type — instead of being read as a literal name."""
        bus = EventBus()
        dp = DamageProcessor(bus)
        attacker = _entity("A")
        target = _entity("T", hp=40)
        weapon = AttackAction(
            name="Sword", description="", bonus_to_hit=0,
            damage=[Damage(DamageType.SLASHING, 0, formula="1d8")],
        )
        # Capture the type the rider actually deals off the damage event.
        seen = []
        bus.subscribe(
            EventType.DAMAGE_INCOMING,
            lambda e: seen.append(e.data.damage_list[0].damage_type),
        )
        rider = [{
            "block": "trigger", "event": "ATTACK_HIT", "holder": "caster",
            "target": "event.defender",
            "then": [{"block": "damage", 
                      "damage_type": "event.action.primary_damage_type",
                      "formula": "1d1"}],
        }]
        _install(bus, dp, attacker, rider)
        bus.emit(
            EventType.ATTACK_HIT,
            AttackHitData(attacker=attacker, defender=target, action=weapon, roll=25),
        )
        assert seen == [DamageType.SLASHING]
