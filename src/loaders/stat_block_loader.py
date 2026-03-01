"""Stat block loading from JSON and YAML."""

import json
from pathlib import Path
from typing import Dict, Any, Optional

from src.models import (
    AbilityScores, StatBlock, AttackAction, SpellAction, Damage, DamageType, Action, ActionType
)


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
        
        # Create stat block
        stat_block = StatBlock(
            name=data.get("name", "Unnamed"),
            ability_scores=ability_scores,
            hit_points=data.get("hit_points", 1),
            hit_points_max=data.get("hit_points_max", 1),
            armor_class=data.get("armor_class", 10),
            proficiency_bonus=data.get("proficiency_bonus", 2),
            actions=actions,
        )
        
        # Add saving throws if provided
        for ability in data.get("saving_throws", []):
            stat_block.saving_throws[ability] = 1
        
        return stat_block
    
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
        
        # Parse damage
        damage = []
        for dmg_data in action_data.get("damage", []):
            dmg_type = DamageType[dmg_data.get("type", "BLUDGEONING").upper()]
            damage.append(Damage(dmg_type, dmg_data.get("amount", 0)))
        
        if action_type == "attack":
            return AttackAction(
                name=name,
                description=description,
                bonus_to_hit=action_data.get("bonus_to_hit", 0),
                damage=damage,
                recharge=recharge,
            )
        elif action_type == "spell":
            return SpellAction(
                name=name,
                description=description,
                spell_level=action_data.get("spell_level", 0),
                save_dc=action_data.get("save_dc", 0),
                spell_attack_bonus=action_data.get("spell_attack_bonus", 0),
                damage=damage,
                recharge=recharge,
            )
        else:
            return Action(
                name=name,
                description=description,
                action_type=ActionType.ABILITY,
                recharge=recharge,
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
            "hit_points": stat_block.hit_points,
            "hit_points_max": stat_block.hit_points_max,
            "armor_class": stat_block.armor_class,
            "proficiency_bonus": stat_block.proficiency_bonus,
            "saving_throws": list(stat_block.saving_throws.keys()),
            "actions": [
                {
                    "name": action.name,
                    "description": action.description,
                    "type": action.action_type.value if hasattr(action, 'action_type') else "ability",
                }
                for action in stat_block.actions
            ],
        }
