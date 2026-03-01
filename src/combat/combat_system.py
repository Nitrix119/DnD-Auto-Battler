"""Main combat simulation system."""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum

from src.models.entity import Entity
from src.models.damage import Damage, DamageType
from src.models.action import AttackAction, SpellAction
from src.models.condition import Condition, ConditionType
from src.utils.dice import roll_d20, roll_dice
from .enums import CombatState
from .initiative import InitiativeTracker


@dataclass
class CombatLog:
    """A single entry in the combat log.
    
    Attributes:
        round_num: The round this occurred
        turn_num: The turn within the round
        actor: The entity performing the action
        action: Description of what happened
    """
    round_num: int
    turn_num: int
    actor: Entity
    action: str


class CombatSystem:
    """Main combat simulator for D&D battles.
    
    Manages turn order, action resolution, and damage calculation.
    """
    
    def __init__(self) -> None:
        """Initialize a new combat encounter."""
        self.state: CombatState = CombatState.SETUP
        self.initiative_tracker: InitiativeTracker = InitiativeTracker()
        self.round: int = 0
        self.turn: int = 0
        self.combatants: List[Entity] = []
        self.log: List[CombatLog] = []
    
    def add_combatant(self, entity: Entity, initiative_modifier: int = 0) -> None:
        """Add an entity to combat.
        
        Args:
            entity: The entity to add
            initiative_modifier: Optional modifier to initiative
        """
        if self.state != CombatState.SETUP:
            raise RuntimeError("Cannot add combatants after combat has started")
        
        self.combatants.append(entity)
        self.initiative_tracker.add_entity(entity, initiative_modifier)
    
    def start_combat(self) -> None:
        """Begin combat with all added entities."""
        if self.state != CombatState.SETUP:
            raise RuntimeError("Combat already started")
        if len(self.combatants) < 2:
            raise ValueError("Need at least 2 combatants")
        
        self.state = CombatState.ACTIVE
        self.round = 1
        self.turn = 1
        self._log_action(self.initiative_tracker.get_current_entity(), 
                        "Combat started!")
    
    def resolve_attack(self, attacker: Entity, defender: Entity, 
                       action: AttackAction) -> Tuple[bool, int]:
        """Resolve an attack roll and damage.
        
        Args:
            attacker: Entity making the attack
            defender: Entity being attacked
            action: The attack action
            
        Returns:
            Tuple of (hit, total_damage)
        """
        # Attack roll
        attack_roll = roll_d20()
        attack_total = attack_roll + action.bonus_to_hit
        
        # Determine if hit
        hit = attack_total >= defender.ac
        
        # Calculate damage
        total_damage = 0
        if hit or not action.damage:
            for damage in action.damage:
                # TODO: Parse and roll formula if present
                total_damage += damage.amount
        
        # Apply damage
        if hit:
            defender.take_damage(total_damage)
            self._log_action(attacker, 
                           f"attacked {defender.name} with {action.name}. "
                           f"Attack: {attack_roll}+{action.bonus_to_hit}={attack_total} vs AC {defender.ac}. "
                           f"Hit! Damage: {total_damage}")
        else:
            self._log_action(attacker,
                           f"attacked {defender.name} with {action.name}. "
                           f"Attack: {attack_roll}+{action.bonus_to_hit}={attack_total} vs AC {defender.ac}. "
                           f"Miss!")
        
        return hit, total_damage
    
    def resolve_saving_throw(self, defender: Entity, ability: str, 
                            dc: int) -> Tuple[int, bool]:
        """Resolve a saving throw.
        
        Args:
            defender: Entity making the save
            ability: The ability for the save
            dc: The DC of the save
            
        Returns:
            Tuple of (save_roll_total, success)
        """
        roll = roll_d20()
        bonus = defender.stat_block.get_saving_throw_bonus(ability)
        total = roll + bonus
        
        success = total >= dc
        return total, success
    
    def end_turn(self) -> None:
        """End the current entity's turn and advance to the next."""
        next_entity = self.initiative_tracker.next_turn()
        self.turn += 1
        
        # If we've gone through all entities, increment round
        if self.initiative_tracker.current_turn_index == 0:
            self.round += 1
            self.turn = 1
        
        # Check for alive combatants
        alive_combatants = [c for c in self.combatants if c.is_alive()]
        if len(alive_combatants) <= 1:
            self.end_combat()
        else:
            self._log_action(next_entity, "takes turn")
    
    def end_combat(self) -> None:
        """End the combat encounter."""
        self.state = CombatState.ENDED
        alive = [c for c in self.combatants if c.is_alive()]
        
        if len(alive) == 1:
            self._log_action(alive[0], f"wins the battle!")
        elif len(alive) == 0:
            self._log_action(None, "Combat ended with no survivors")
        else:
            self._log_action(None, "Combat ended")
    
    def get_current_entity(self) -> Optional[Entity]:
        """Get the entity whose turn it is."""
        return self.initiative_tracker.get_current_entity()
    
    def get_alive_entities(self) -> List[Entity]:
        """Get all entities still in the fight."""
        return [e for e in self.combatants if e.is_alive()]
    
    def get_enemies(self, entity: Entity) -> List[Entity]:
        """Get all enemies of a given entity.
        
        For now, this returns all other alive entities.
        Future versions could support teams.
        
        Args:
            entity: The entity to find enemies for
            
        Returns:
            List of enemies
        """
        return [e for e in self.get_alive_entities() if e != entity]
    
    def _log_action(self, actor: Optional[Entity], action: str) -> None:
        """Log an action to the combat log.
        
        Args:
            actor: The entity performing the action
            action: Description of the action
        """
        entry = CombatLog(self.round, self.turn, actor, action)
        self.log.append(entry)
    
    def get_combat_log(self) -> List[str]:
        """Get a formatted combat log.
        
        Returns:
            List of formatted log entries
        """
        formatted = []
        for entry in self.log:
            actor_name = entry.actor.name if entry.actor else "System"
            formatted.append(f"R{entry.round_num}T{entry.turn_num} [{actor_name}] {entry.action}")
        return formatted
