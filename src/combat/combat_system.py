"""Main combat simulation system."""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum

from src.models.entity import Entity
from src.models.action import Action, AttackAction, SpellAction
from src.utils.dice import roll_d20
from .enums import CombatState
from .event_bus import EventBus
from .initiative import InitiativeTracker
from .damage_processor import DamageProcessor
from .attack_resolver import AttackResolver
from .spell_resolver import SpellResolver
from .turn_manager import TurnManager


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
    Delegates to focused collaborators for specific concerns.
    """

    def __init__(self) -> None:
        """Initialize a new combat encounter."""
        self.state: CombatState = CombatState.SETUP
        self.initiative_tracker: InitiativeTracker = InitiativeTracker()
        self.combatants: List[Entity] = []
        self.log: List[CombatLog] = []
        self._turn_manager: Optional[TurnManager] = None
        self.event_bus: EventBus = EventBus()

    @property
    def event_bus(self) -> EventBus:
        """The event bus for this combat."""
        return self._event_bus

    @event_bus.setter
    def event_bus(self, bus: EventBus) -> None:
        self._event_bus = bus
        self._damage_processor = DamageProcessor(bus)
        self._attack_resolver = AttackResolver(bus, self._damage_processor)
        self._spell_resolver = SpellResolver(bus, self._damage_processor, self._attack_resolver)
        # Preserve any previously set rule_engine across bus re-assignments
        if hasattr(self, "_rule_engine") and self._rule_engine is not None:
            self._spell_resolver.rule_engine = self._rule_engine

    @property
    def rule_engine(self):
        """The rule engine used for spell effect application."""
        return getattr(self, "_rule_engine", None)

    @rule_engine.setter
    def rule_engine(self, engine) -> None:
        self._rule_engine = engine
        self._spell_resolver.rule_engine = engine

    @property
    def round(self) -> int:
        """Current round number."""
        return self._turn_manager.round if self._turn_manager else 0

    @property
    def turn(self) -> int:
        """Current turn number within the round."""
        return self._turn_manager.turn if self._turn_manager else 0

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
        self._turn_manager = TurnManager(
            self.event_bus, self.initiative_tracker, self.combatants,
        )
        self._log_action(self.initiative_tracker.get_current_entity(),
                        "Combat started!")
        self._turn_manager.start()

    def resolve_attack(self, attacker: Entity, defender: Entity,
                       action: AttackAction) -> Tuple[bool, int]:
        """Resolve an attack roll and damage.

        Args:
            attacker: Entity making the attack
            defender: Entity being attacked
            action: The attack action

        Returns:
            Tuple of (hit, total_damage)

        Raises:
            ValueError: If the attacker cannot afford the action's cost.
        """
        if not attacker.can_afford(action.cost):
            raise ValueError(
                f"{attacker.name} cannot afford {action.name}: "
                f"have {attacker.resources}, need {action.cost}"
            )
        attacker.spend_resources(action.cost)

        hit, total_damage, log_msg = self._attack_resolver.resolve(
            attacker, defender, action,
        )
        if log_msg:
            self._log_action(attacker, log_msg)
        return hit, total_damage

    def resolve_spell(self, caster: Entity, defenders: List[Entity],
                      action: SpellAction) -> List[Tuple[bool, int]]:
        """Resolve a spell action against one or more targets.

        Args:
            caster: Entity casting the spell
            defenders: Entities the spell is targeting
            action: The spell action being resolved

        Returns:
            List of (hit, damage_dealt) per defender, in the same order as
            defenders.

        Raises:
            ValueError: If the caster cannot afford the spell's cost.
        """
        if not caster.can_afford(action.cost):
            raise ValueError(
                f"{caster.name} cannot afford {action.name}: "
                f"have {caster.resources}, need {action.cost}"
            )
        caster.spend_resources(action.cost)

        results = self._spell_resolver.resolve(caster, defenders, action)
        for _, _, log_msg in results:
            if log_msg:
                self._log_action(caster, log_msg)
        return [(hit, damage) for hit, damage, _ in results]

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
        should_continue = self._turn_manager.end_turn()
        if not should_continue:
            self.end_combat()
        else:
            self._log_action(self._turn_manager.get_current_entity(), "takes turn")

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

    def get_affordable_actions(self, entity: Entity) -> List[Action]:
        """Return actions the entity can currently afford."""
        return [a for a in entity.stat_block.actions if entity.can_afford(a.cost)]

    def get_enemies(self, entity: Entity) -> List[Entity]:
        """Get all alive enemies of a given entity.

        When *entity.team* is set, enemies are entities on a different team
        (or with no team).  When *entity.team* is ``None``, all other alive
        entities are considered enemies.
        """
        if entity.team is None:
            return [e for e in self.get_alive_entities() if e != entity]
        return [e for e in self.get_alive_entities()
                if e != entity and e.team != entity.team]

    def get_allies(self, entity: Entity) -> List[Entity]:
        """Get all alive allies of a given entity (same team, excluding self).

        Returns an empty list if *entity.team* is ``None``.
        """
        if entity.team is None:
            return []
        return [e for e in self.get_alive_entities()
                if e != entity and e.team == entity.team]

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
