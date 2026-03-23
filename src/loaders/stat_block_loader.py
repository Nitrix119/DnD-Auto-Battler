"""Stat block loading from JSON and YAML."""

import json
from pathlib import Path
from typing import Dict, Any, Optional

from src.models import (
    AbilityScores, StatBlock, AttackAction, SpellAction, Damage, DamageType,
    Action, ActionType, ActionCost,
    RangeType, SpellRange,
    TargetingType,
    AOEShape, AOEProperties,
    CastingTimeType, CastingTime,
    DurationUnit, Duration,
    SpellComponents,
)
from src.models.creature_size import CreatureSize
from src.models.stat_block import DEFAULT_RESOURCE_DEFAULTS


class StatBlockLoader:
    """Loads stat blocks from JSON files."""

    @staticmethod
    def load_from_json(filepath: str) -> StatBlock:
        """Load a stat block from a JSON file.

        Args:
            filepath: Path to the JSON file

        Returns:
            Loaded StatBlock

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If JSON is invalid
        """
        with open(filepath, 'r') as f:
            data = json.load(f)
        return StatBlockLoader.from_dict(data)

    @staticmethod
    def load_spell_from_json(filepath: str) -> SpellAction:
        """Load a single SpellAction from a JSON file.

        The file should contain one action-object at the top level
        (the same structure used inside a stat block's ``actions`` list,
        with ``"type": "spell"``).

        Args:
            filepath: Path to the JSON spell file

        Returns:
            Parsed SpellAction

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If the action is not a spell
        """
        with open(filepath, 'r') as f:
            data = json.load(f)
        action = StatBlockLoader._parse_action(data)
        if not isinstance(action, SpellAction):
            raise ValueError(f"Expected a spell action in {filepath!r}")
        return action

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> StatBlock:
        """Create a StatBlock from a dictionary.

        Args:
            data: Dictionary with stat block data

        Returns:
            Loaded StatBlock
        """
        # Parse ability scores
        abilities = data.get("abilities", {})
        ability_scores = AbilityScores(
            strength=abilities.get("strength", 10),
            dexterity=abilities.get("dexterity", 10),
            constitution=abilities.get("constitution", 10),
            intelligence=abilities.get("intelligence", 10),
            wisdom=abilities.get("wisdom", 10),
            charisma=abilities.get("charisma", 10),
        )

        # Parse actions
        actions = []
        for action_data in data.get("actions", []):
            action = StatBlockLoader._parse_action(action_data)
            if action:
                actions.append(action)

        # Parse resource defaults (action economy)
        resource_defaults = dict(DEFAULT_RESOURCE_DEFAULTS)
        if "resource_defaults" in data:
            resource_defaults.update(data["resource_defaults"])

        # Parse creature size (default MEDIUM)
        size_str = data.get("size", "medium").lower()
        try:
            creature_size = CreatureSize[size_str.upper()]
        except KeyError:
            creature_size = CreatureSize.MEDIUM

        # Create stat block (template — current HP lives on Entity)
        hp_max = data.get("hit_points_max", data.get("hit_points", 1))
        stat_block = StatBlock(
            name=data.get("name", "Unnamed"),
            ability_scores=ability_scores,
            hit_points_max=hp_max,
            armor_class=data.get("armor_class", 10),
            proficiency_bonus=data.get("proficiency_bonus", 2),
            actions=actions,
            resource_defaults=resource_defaults,
            size=creature_size,
            known_spells=list(data.get("known_spells", [])),
            spellcasting_ability=data.get("spellcasting_ability", ""),
        )

        # Add saving throws if provided
        for ability in data.get("saving_throws", []):
            stat_block.saving_throws[ability] = 1

        return stat_block

    @staticmethod
    def _parse_damage(action_data: Dict[str, Any]) -> list:
        """Parse the damage list from an action dictionary."""
        damage = []
        for dmg_data in action_data.get("damage", []):
            dmg_type = DamageType[dmg_data.get("type", "BLUDGEONING").upper()]
            damage.append(Damage(
                dmg_type,
                dmg_data.get("amount", 0),
                formula=dmg_data.get("formula"),
            ))
        return damage

    @staticmethod
    def _parse_spell_range(data: Dict[str, Any]) -> SpellRange:
        """Parse a spell range dict into a SpellRange."""
        range_type = RangeType[data.get("type", "touch").upper()]
        return SpellRange(range_type, distance_ft=data.get("distance_ft"))

    @staticmethod
    def _parse_casting_time(data: Dict[str, Any]) -> CastingTime:
        """Parse a casting_time dict into a CastingTime."""
        ct_type = CastingTimeType[data.get("type", "action").upper()]
        return CastingTime(
            ct_type,
            count=data.get("count", 1),
            reaction_trigger=data.get("reaction_trigger"),
            special_description=data.get("special_description"),
        )

    @staticmethod
    def _parse_duration(data: Dict[str, Any]) -> Duration:
        """Parse a duration dict into a Duration."""
        unit = DurationUnit[data.get("unit", "instantaneous").upper()]
        return Duration(
            unit,
            count=data.get("count", 1),
            concentration=data.get("concentration", False),
            special_description=data.get("special_description"),
        )

    @staticmethod
    def _parse_components(data: Dict[str, Any]) -> SpellComponents:
        """Parse a components dict into a SpellComponents."""
        return SpellComponents(
            verbal=data.get("verbal", True),
            somatic=data.get("somatic", True),
            material=data.get("material", []),
        )

    @staticmethod
    def _parse_cost(data: Dict[str, Any]) -> Optional[ActionCost]:
        """Parse an optional cost dict into an ActionCost, or None if absent."""
        cost_data = data.get("cost")
        if cost_data is None:
            return None
        return ActionCost(
            actions=cost_data.get("actions", 0),
            bonus_actions=cost_data.get("bonus_actions", 0),
            reactions=cost_data.get("reactions", 0),
            movement=cost_data.get("movement", 0),
        )

    @staticmethod
    def _parse_action(action_data: Dict[str, Any]) -> Optional[Action]:
        """Parse an action from dictionary data.

        Args:
            action_data: Dictionary with action data

        Returns:
            Parsed action or None if invalid
        """
        action_type = action_data.get("type", "").lower()
        name = action_data.get("name", "Unknown")
        description = action_data.get("description", "")
        recharge = action_data.get("recharge")
        cost = StatBlockLoader._parse_cost(action_data)

        damage = StatBlockLoader._parse_damage(action_data)

        cost_kwargs: Dict[str, Any] = {}
        if cost is not None:
            cost_kwargs["cost"] = cost

        if action_type == "attack":
            return AttackAction(
                name=name,
                description=description,
                bonus_to_hit=action_data.get("bonus_to_hit", 0),
                damage=damage,
                recharge=recharge,
                range_ft=float(action_data.get("range_ft", 5.0)),
                **cost_kwargs,
            )

        if action_type == "spell":
            range_data = action_data.get("spell_range", {})
            spell_range = (
                StatBlockLoader._parse_spell_range(range_data)
                if range_data
                else SpellRange(RangeType.TOUCH)
            )

            targeting_type = TargetingType[
                action_data.get("targeting_type", "single_target").upper()
            ]

            aoe = None
            aoe_data = action_data.get("aoe")
            if aoe_data:
                shape = AOEShape[aoe_data.get("shape", "sphere").upper()]
                aoe = AOEProperties(shape, aoe_data.get("size_ft", 5))

            ct_data = action_data.get("casting_time", {})
            casting_time = (
                StatBlockLoader._parse_casting_time(ct_data)
                if ct_data
                else CastingTime(CastingTimeType.ACTION)
            )

            dur_data = action_data.get("duration", {})
            duration = (
                StatBlockLoader._parse_duration(dur_data)
                if dur_data
                else Duration(DurationUnit.INSTANTANEOUS)
            )

            comp_data = action_data.get("components", {})
            components = (
                StatBlockLoader._parse_components(comp_data)
                if comp_data
                else SpellComponents(verbal=True, somatic=True)
            )

            return SpellAction(
                name=name,
                description=description,
                spell_level=action_data.get("spell_level", 0),
                save_dc=action_data.get("save_dc", 0),
                save_ability=action_data.get("save_ability", ""),
                spell_attack_bonus=action_data.get("spell_attack_bonus", 0),
                damage=damage,
                recharge=recharge,
                spell_range=spell_range,
                targeting_type=targeting_type,
                aoe=aoe,
                casting_time=casting_time,
                duration=duration,
                components=components,
                higher_level_scaling=action_data.get("higher_level_scaling"),
                can_target_self=action_data.get("can_target_self", False),
                animation=action_data.get("animation", []),
                spell_effects=action_data.get("effects", []),
                on_successful_save=action_data.get("on_successful_save", []),
                on_failed_save=action_data.get("on_failed_save", []),
                **cost_kwargs,
            )

        # Fallback: generic ability action
        return Action(
            name=name,
            description=description,
            action_type=ActionType.ABILITY,
            recharge=recharge,
            **cost_kwargs,
        )

    @staticmethod
    def save_to_json(stat_block: StatBlock, filepath: str) -> None:
        """Save a stat block to JSON.

        Args:
            stat_block: The stat block to save
            filepath: Path to save to
        """
        data = StatBlockLoader.to_dict(stat_block)
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def _serialize_action(action: Action) -> Dict[str, Any]:
        """Serialize a single action to a dictionary."""
        base: Dict[str, Any] = {
            "name": action.name,
            "description": action.description,
            "type": action.action_type.value,
        }
        if action.recharge:
            base["recharge"] = action.recharge

        # Serialize cost (omit if all zeros — the default is derived by the Action class)
        from src.models.action_resources import NO_COST
        if action.cost != NO_COST:
            cost_dict: Dict[str, Any] = {}
            if action.cost.actions:
                cost_dict["actions"] = action.cost.actions
            if action.cost.bonus_actions:
                cost_dict["bonus_actions"] = action.cost.bonus_actions
            if action.cost.reactions:
                cost_dict["reactions"] = action.cost.reactions
            if action.cost.movement:
                cost_dict["movement"] = action.cost.movement
            if cost_dict:
                base["cost"] = cost_dict

        if isinstance(action, AttackAction):
            base["bonus_to_hit"] = action.bonus_to_hit
            base["range_ft"] = action.range_ft
            if action.damage:
                base["damage"] = [
                    {
                        "type": d.damage_type.name,
                        "amount": d.amount,
                        **({"formula": d.formula} if d.formula else {}),
                    }
                    for d in action.damage
                ]
            if action.damage_half_on_save:
                base["damage_half_on_save"] = list(action.damage_half_on_save)

        elif isinstance(action, SpellAction):
            base["spell_level"] = action.spell_level
            base["save_dc"] = action.save_dc
            base["spell_attack_bonus"] = action.spell_attack_bonus
            if action.damage:
                base["damage"] = [
                    {
                        "type": d.damage_type.name,
                        "amount": d.amount,
                        **({"formula": d.formula} if d.formula else {}),
                    }
                    for d in action.damage
                ]

            # spell_range
            sr = action.spell_range
            range_dict: Dict[str, Any] = {"type": sr.range_type.value}
            if sr.distance_ft is not None:
                range_dict["distance_ft"] = sr.distance_ft
            base["spell_range"] = range_dict

            base["targeting_type"] = action.targeting_type.value

            if action.aoe:
                base["aoe"] = {
                    "shape": action.aoe.shape.value,
                    "size_ft": action.aoe.size_ft,
                }

            # casting_time
            ct = action.casting_time
            ct_dict: Dict[str, Any] = {
                "type": ct.time_type.value,
                "count": ct.count,
            }
            if ct.reaction_trigger:
                ct_dict["reaction_trigger"] = ct.reaction_trigger
            if ct.special_description:
                ct_dict["special_description"] = ct.special_description
            base["casting_time"] = ct_dict

            # duration
            dur = action.duration
            dur_dict: Dict[str, Any] = {
                "unit": dur.unit.value,
                "count": dur.count,
                "concentration": dur.concentration,
            }
            if dur.special_description:
                dur_dict["special_description"] = dur.special_description
            base["duration"] = dur_dict

            # components
            base["components"] = {
                "verbal": action.components.verbal,
                "somatic": action.components.somatic,
                "material": action.components.material,
            }

            if action.higher_level_scaling:
                base["higher_level_scaling"] = action.higher_level_scaling

            if action.can_target_self:
                base["can_target_self"] = True

            if action.animation:
                base["animation"] = action.animation

        return base

    @staticmethod
    def to_dict(stat_block: StatBlock) -> Dict[str, Any]:
        """Convert a StatBlock to a dictionary.

        Args:
            stat_block: The stat block to convert

        Returns:
            Dictionary representation
        """
        return {
            "name": stat_block.name,
            "abilities": {
                "strength": stat_block.ability_scores.strength,
                "dexterity": stat_block.ability_scores.dexterity,
                "constitution": stat_block.ability_scores.constitution,
                "intelligence": stat_block.ability_scores.intelligence,
                "wisdom": stat_block.ability_scores.wisdom,
                "charisma": stat_block.ability_scores.charisma,
            },
            "hit_points": stat_block.hit_points_max,
            "hit_points_max": stat_block.hit_points_max,
            "armor_class": stat_block.armor_class,
            "proficiency_bonus": stat_block.proficiency_bonus,
            "saving_throws": list(stat_block.saving_throws.keys()),
            "resource_defaults": stat_block.resource_defaults,
            "size": stat_block.size.value,
            "known_spells": list(stat_block.known_spells),
            "actions": [
                StatBlockLoader._serialize_action(action)
                for action in stat_block.actions
            ],
        }
