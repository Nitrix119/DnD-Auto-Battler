"""Main combat simulation system."""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum

from src.models.entity import Entity
from src.models.action import AttackAction, SpellAction
from src.models.condition import Condition, ConditionType
from src.utils.dice import roll_d20, roll_dice, roll_formula
from .enums import CombatState
from .event_bus import EventBus
from .events import EventType
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
        self.event_bus: EventBus = EventBus()
    
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
        self.event_bus.emit(EventType.ROUND_START, round_num=self.round)
        self.event_bus.emit(EventType.TURN_START,
                            entity=self.initiative_tracker.get_current_entity(),
                            round_num=self.round, turn_num=self.turn)
    
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
        # Allow handlers to cancel before the roll (e.g. Shield spell)
        declared = self.event_bus.emit(EventType.ATTACK_DECLARED,
                                       attacker=attacker, defender=defender, action=action)
        if declared.cancelled:
            return False, 0

        # Attack roll
        attack_roll = roll_d20()
        attack_total = attack_roll + action.bonus_to_hit

        # Determine if hit
        hit = attack_total >= defender.ac

        # Roll and apply damage per type
        total_damage = 0
        if hit:
            self.event_bus.emit(EventType.ATTACK_HIT,
                                attacker=attacker, defender=defender,
                                action=action, roll=attack_total)
            was_alive = defender.is_alive()
            rolled_damages = action.roll_damage()
            for d in rolled_damages:
                defender.take_damage(d)
                total_damage += d.amount
            self.event_bus.emit(EventType.DAMAGE_DEALT,
                                defender=defender, damage_list=rolled_damages, total=total_damage)
            if was_alive and not defender.is_alive():
                self.event_bus.emit(EventType.ENTITY_DIES, entity=defender, killer=attacker)
            self._log_action(attacker,
                             f"attacked {defender.name} with {action.name}. "
                             f"Attack: {attack_roll}+{action.bonus_to_hit}={attack_total} vs AC {defender.ac}. "
                             f"Hit! Damage: {total_damage}")
        else:
            self.event_bus.emit(EventType.ATTACK_MISS,
                                attacker=attacker, defender=defender,
                                action=action, roll=attack_total)
            self._log_action(attacker,
                             f"attacked {defender.name} with {action.name}. "
                             f"Attack: {attack_roll}+{action.bonus_to_hit}={attack_total} vs AC {defender.ac}. "
                             f"Miss!")

        return hit, total_damage

    def resolve_spell(self, caster: Entity, defenders: List[Entity],
                      action: SpellAction) -> List[Tuple[bool, int]]:
        """Resolve a spell action against one or more targets.

        Damage is rolled once and applied to every target, matching D&D rules
        (e.g. Fireball rolls 8d6 once and deals that total to each creature
        in the area).

        Spell attack rolls are made per-target when the spell uses them.
        Saving throws are not yet implemented (see TODO below).

        Args:
            caster: Entity casting the spell
            defenders: Entities the spell is targeting
            action: The spell action being resolved

        Returns:
            List of (hit, damage_dealt) per defender, in the same order as
            defenders.
        """
        self.event_bus.emit(EventType.SPELL_CAST, caster=caster, defenders=defenders, action=action)

        # Roll damage once — the same total applies to every target
        rolled_damages = action.roll_damage()
        total_damage = sum(d.amount for d in rolled_damages)

        # TODO: Implement saving throws (action.save_dc > 0).  Currently all
        #       targets with a save DC are treated as if they failed the save
        #       and take full damage.

        results: List[Tuple[bool, int]] = []
        for defender in defenders:
            if action.spell_attack_bonus != 0 and action.save_dc == 0:
                # Spell requires an attack roll (e.g. Fire Bolt, Chromatic Orb)
                attack_roll = roll_d20()
                attack_total = attack_roll + action.spell_attack_bonus
                hit = attack_total >= defender.ac

                damage_dealt = total_damage if hit else 0
                if hit:
                    self.event_bus.emit(EventType.SPELL_HIT,
                                        caster=caster, defender=defender,
                                        action=action, roll=attack_total)
                    was_alive = defender.is_alive()
                    for d in rolled_damages:
                        defender.take_damage(d)
                    self.event_bus.emit(EventType.DAMAGE_DEALT,
                                        defender=defender, damage_list=rolled_damages,
                                        total=damage_dealt)
                    if was_alive and not defender.is_alive():
                        self.event_bus.emit(EventType.ENTITY_DIES, entity=defender, killer=caster)

                hit_str = f"Hit! Damage: {damage_dealt}" if hit else "Miss!"
                self._log_action(
                    caster,
                    f"cast {action.name} at {defender.name}. "
                    f"Spell attack: {attack_roll}+{action.spell_attack_bonus}"
                    f"={attack_total} vs AC {defender.ac}. {hit_str}"
                )
            else:
                # No attack roll — auto-hit (saving throws via TODO above)
                hit = True
                damage_dealt = total_damage
                self.event_bus.emit(EventType.SPELL_HIT,
                                    caster=caster, defender=defender, action=action, roll=None)
                was_alive = defender.is_alive()
                for d in rolled_damages:
                    defender.take_damage(d)
                self.event_bus.emit(EventType.DAMAGE_DEALT,
                                    defender=defender, damage_list=rolled_damages, total=damage_dealt)
                if was_alive and not defender.is_alive():
                    self.event_bus.emit(EventType.ENTITY_DIES, entity=defender, killer=caster)

                self._log_action(
                    caster,
                    f"cast {action.name} at {defender.name}. "
                    f"Damage: {damage_dealt}"
                )

            results.append((hit, damage_dealt))

        return results

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
        current_entity = self.initiative_tracker.get_current_entity()
        self.event_bus.emit(EventType.TURN_END,
                            entity=current_entity, round_num=self.round, turn_num=self.turn)

        next_entity = self.initiative_tracker.next_turn()
        self.turn += 1

        # If we've gone through all entities, increment round
        if self.initiative_tracker.current_turn_index == 0:
            self.event_bus.emit(EventType.ROUND_END, round_num=self.round)
            self.round += 1
            self.turn = 1
            self.event_bus.emit(EventType.ROUND_START, round_num=self.round)

        # Check for alive combatants
        alive_combatants = [c for c in self.combatants if c.is_alive()]
        if len(alive_combatants) <= 1:
            self.end_combat()
        else:
            self.event_bus.emit(EventType.TURN_START,
                                entity=next_entity, round_num=self.round, turn_num=self.turn)
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
