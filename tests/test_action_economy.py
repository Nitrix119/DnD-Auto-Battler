"""Tests for the action economy system."""

import pytest
from src.models import (
    AbilityScores, StatBlock, Entity, AttackAction, SpellAction,
    Damage, DamageType, ActionCost, ActionResources,
    ACTION_COST, BONUS_ACTION_COST, REACTION_COST, NO_COST,
    CastingTimeType, CastingTime,
)
from src.combat import CombatSystem, CombatState
from src.combat.event_bus import EventBus
from src.combat.events import EventType
from src.combat.event_data import TurnEventData
from src.rules.rule_engine import RuleEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stat_block(name="Test", hp=30, ac=15, **kwargs):
    abilities = AbilityScores(14, 14, 14, 10, 10, 10)
    return StatBlock(
        name=name,
        ability_scores=abilities,
        hit_points_max=hp,
        armor_class=ac,
        **kwargs,
    )


def _make_attack(name="Sword", bonus=5, cost=None):
    kwargs = dict(
        name=name,
        description="A weapon attack",
        bonus_to_hit=bonus,
        damage=[Damage(DamageType.SLASHING, 6, formula="1d6")],
    )
    if cost is not None:
        kwargs["cost"] = cost
    return AttackAction(**kwargs)


# ---------------------------------------------------------------------------
# ActionCost / ActionResources unit tests
# ---------------------------------------------------------------------------

class TestActionCost:
    def test_defaults_are_zero(self):
        cost = ActionCost()
        assert cost.actions == 0
        assert cost.bonus_actions == 0
        assert cost.reactions == 0
        assert cost.movement == 0

    def test_constants(self):
        assert ACTION_COST == ActionCost(actions=1)
        assert BONUS_ACTION_COST == ActionCost(bonus_actions=1)
        assert REACTION_COST == ActionCost(reactions=1)
        assert NO_COST == ActionCost()

    def test_frozen(self):
        with pytest.raises(AttributeError):
            ACTION_COST.actions = 2


class TestActionResources:
    def test_defaults(self):
        r = ActionResources()
        assert r.actions == 1
        assert r.bonus_actions == 1
        assert r.reactions == 1
        assert r.movement == 30

    def test_can_afford_true(self):
        r = ActionResources()
        assert r.can_afford(ACTION_COST)
        assert r.can_afford(BONUS_ACTION_COST)
        assert r.can_afford(NO_COST)

    def test_can_afford_false(self):
        r = ActionResources(actions=0)
        assert not r.can_afford(ACTION_COST)

    def test_can_afford_combination(self):
        r = ActionResources()
        combo = ActionCost(actions=1, bonus_actions=1)
        assert r.can_afford(combo)
        r.actions = 0
        assert not r.can_afford(combo)

    def test_spend_deducts(self):
        r = ActionResources()
        r.spend(ACTION_COST)
        assert r.actions == 0
        assert r.bonus_actions == 1

    def test_spend_raises_on_insufficient(self):
        r = ActionResources(actions=0)
        with pytest.raises(ValueError):
            r.spend(ACTION_COST)

    def test_spend_movement(self):
        r = ActionResources(movement=30)
        r.spend(ActionCost(movement=15))
        assert r.movement == 15
        assert r.can_afford(ActionCost(movement=15))
        assert not r.can_afford(ActionCost(movement=16))


# ---------------------------------------------------------------------------
# Entity resource management
# ---------------------------------------------------------------------------

class TestEntityResources:
    def test_default_resources(self):
        sb = _make_stat_block()
        entity = Entity(sb)
        assert entity.resources.actions == 1
        assert entity.resources.bonus_actions == 1
        assert entity.resources.reactions == 1
        assert entity.resources.movement == 30

    def test_custom_resource_defaults(self):
        sb = _make_stat_block(
            resource_defaults={"actions": 2, "bonus_actions": 1, "reactions": 1, "speed": 40},
        )
        entity = Entity(sb)
        assert entity.resources.actions == 2
        assert entity.resources.movement == 40

    def test_can_afford_and_spend(self):
        entity = Entity(_make_stat_block())
        assert entity.can_afford(ACTION_COST)
        entity.spend_resources(ACTION_COST)
        assert not entity.can_afford(ACTION_COST)

    def test_refill_resources(self):
        entity = Entity(_make_stat_block())
        entity.spend_resources(ACTION_COST)
        entity.spend_resources(BONUS_ACTION_COST)
        assert entity.resources.actions == 0
        assert entity.resources.bonus_actions == 0

        entity.refill_resources()
        assert entity.resources.actions == 1
        assert entity.resources.bonus_actions == 1

    def test_add_resource_overfill(self):
        entity = Entity(_make_stat_block())
        entity.add_resource("actions", 1)
        assert entity.resources.actions == 2

    def test_refill_resets_overfill(self):
        entity = Entity(_make_stat_block())
        entity.add_resource("actions", 2)
        assert entity.resources.actions == 3
        entity.refill_resources()
        assert entity.resources.actions == 1


# ---------------------------------------------------------------------------
# Action cost field and spell auto-derive
# ---------------------------------------------------------------------------

class TestActionCostField:
    def test_attack_default_cost(self):
        attack = _make_attack()
        assert attack.cost == ACTION_COST

    def test_attack_explicit_cost(self):
        cost = BONUS_ACTION_COST
        attack = _make_attack(cost=cost)
        assert attack.cost == cost

    def test_spell_action_derives_from_casting_time(self):
        spell = SpellAction(
            name="Healing Word",
            description="A healing spell",
            casting_time=CastingTime(CastingTimeType.BONUS_ACTION),
        )
        assert spell.cost == BONUS_ACTION_COST

    def test_spell_action_default_is_action(self):
        spell = SpellAction(
            name="Fire Bolt",
            description="A fire cantrip",
            casting_time=CastingTime(CastingTimeType.ACTION),
        )
        assert spell.cost == ACTION_COST

    def test_spell_reaction_cost(self):
        spell = SpellAction(
            name="Shield",
            description="A reaction spell",
            casting_time=CastingTime(CastingTimeType.REACTION),
        )
        assert spell.cost == REACTION_COST

    def test_spell_explicit_cost_overrides(self):
        custom_cost = ActionCost(actions=1, bonus_actions=1)
        spell = SpellAction(
            name="Special",
            description="A special spell",
            casting_time=CastingTime(CastingTimeType.BONUS_ACTION),
            cost=custom_cost,
        )
        assert spell.cost == custom_cost


# ---------------------------------------------------------------------------
# CombatSystem enforcement
# ---------------------------------------------------------------------------

class TestCombatSystemResourceEnforcement:
    @pytest.fixture
    def combat_pair(self):
        sb1 = _make_stat_block("Fighter", hp=50, ac=16)
        sb2 = _make_stat_block("Goblin", hp=20, ac=12)
        e1 = Entity(sb1)
        e2 = Entity(sb2)
        combat = CombatSystem()
        combat.add_combatant(e1)
        combat.add_combatant(e2)
        combat.start_combat()
        # Ensure Fighter (e1) is always the active entity regardless of initiative roll.
        for i, entry in enumerate(combat.initiative_tracker.initiative_order):
            if entry.entity is e1:
                combat.initiative_tracker.current_turn_index = i
                break
        return combat, e1, e2

    def test_resolve_attack_spends_resources(self, combat_pair):
        combat, fighter, goblin = combat_pair
        attack = _make_attack()
        assert fighter.resources.actions == 1
        combat.resolve_attack(fighter, goblin, attack)
        assert fighter.resources.actions == 0

    def test_resolve_attack_fails_without_resources(self, combat_pair):
        combat, fighter, goblin = combat_pair
        attack = _make_attack()
        fighter.spend_resources(ACTION_COST)
        with pytest.raises(ValueError, match="cannot afford"):
            combat.resolve_attack(fighter, goblin, attack)

    def test_resolve_spell_spends_resources(self, combat_pair):
        combat, fighter, goblin = combat_pair
        spell = SpellAction(
            name="Fire Bolt",
            description="Cantrip",
            program=[
                {"block": "attack_roll", "attack_bonus": "use_caster_bonus", "target": "defender"},
                {"block": "damage", "target": "defender", "damage_type": "FIRE", "formula": "1d10", "requires_hit": True},
            ],
        )
        combat.resolve_spell(fighter, [goblin], spell)
        assert fighter.resources.actions == 0

    def test_resolve_spell_fails_without_resources(self, combat_pair):
        combat, fighter, goblin = combat_pair
        spell = SpellAction(
            name="Fire Bolt",
            description="Cantrip",
            program=[
                {"block": "attack_roll", "attack_bonus": "use_caster_bonus", "target": "defender"},
            ],
        )
        fighter.spend_resources(ACTION_COST)
        with pytest.raises(ValueError, match="cannot afford"):
            combat.resolve_spell(fighter, [goblin], spell)

    def test_get_affordable_actions(self, combat_pair):
        combat, fighter, goblin = combat_pair
        attack = _make_attack()
        bonus_attack = _make_attack("Offhand", cost=BONUS_ACTION_COST)
        fighter.stat_block.actions = [attack, bonus_attack]

        affordable = combat.get_affordable_actions(fighter)
        assert len(affordable) == 2

        fighter.spend_resources(ACTION_COST)
        affordable = combat.get_affordable_actions(fighter)
        assert len(affordable) == 1
        assert affordable[0].name == "Offhand"


# ---------------------------------------------------------------------------
# Refill game rule integration
# ---------------------------------------------------------------------------

class TestRefillRule:
    def test_refill_on_turn_start(self):
        """Resources are refilled when TURN_START fires with the refill rule loaded."""
        bus = EventBus()
        engine = RuleEngine(bus)
        engine.load_from_file("rules/global/action_economy_refill.json")

        entity = Entity(_make_stat_block())
        entity.spend_resources(ACTION_COST)
        entity.spend_resources(BONUS_ACTION_COST)
        assert entity.resources.actions == 0

        bus.emit(EventType.TURN_START, TurnEventData(
            entity=entity, round_num=1, turn_num=1,
        ))
        assert entity.resources.actions == 1
        assert entity.resources.bonus_actions == 1



# ---------------------------------------------------------------------------
# StatBlockLoader round-trip
# ---------------------------------------------------------------------------

class TestLoaderRoundTrip:
    def test_resource_defaults_round_trip(self):
        from src.loaders.stat_block_loader import StatBlockLoader

        original = _make_stat_block(
            resource_defaults={"actions": 2, "bonus_actions": 1, "reactions": 1, "speed": 40},
        )
        data = StatBlockLoader.to_dict(original)
        assert data["resource_defaults"]["actions"] == 2
        assert data["resource_defaults"]["speed"] == 40

        loaded = StatBlockLoader.from_dict(data)
        assert loaded.resource_defaults["actions"] == 2
        assert loaded.resource_defaults["speed"] == 40

    def test_action_cost_round_trip(self):
        from src.loaders.stat_block_loader import StatBlockLoader

        action_data = {
            "name": "Offhand Strike",
            "description": "A bonus action attack",
            "type": "attack",
            "bonus_to_hit": 4,
            "damage": [{"type": "SLASHING", "amount": 4, "formula": "1d4"}],
            "cost": {"bonus_actions": 1},
        }
        action = StatBlockLoader._parse_action(action_data)
        assert action.cost == BONUS_ACTION_COST

        serialized = StatBlockLoader._serialize_action(action)
        assert serialized["cost"] == {"bonus_actions": 1}
