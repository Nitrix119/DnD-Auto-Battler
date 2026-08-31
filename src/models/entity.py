"""Entity class representing a combatant in battle."""

from dataclasses import dataclass, field
from typing import Optional, List
import uuid

from .action_resources import ActionCost, ActionResources
from .action import Action
from .stat_block import StatBlock
from .condition import Condition, ConditionType
from .damage import Damage
from .stat_modifier import StatModifier
from .spell_slots import SpellSlots
from .legendary_actions import LegendaryActions
from .lifetime import LifetimeScope, RevokeHandle


@dataclass
class Entity:
    """A combatant in battle (character or creature).

    Mutable combat state (HP, conditions) lives here.  The underlying
    :class:`StatBlock` is treated as an immutable template so that multiple
    entities can safely share the same stat block.
    """

    stat_block: StatBlock
    entity_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    initiative_roll: Optional[int] = None
    is_player_controlled: bool = False
    current_hp: Optional[int] = None  # None → set to max in __post_init__
    temporary_hp: int = 0
    conditions: List[Condition] = field(default_factory=list)
    team: Optional[str] = None  # faction/team identifier; None = hostile to everyone
    concentrating_on: Optional[str] = None
    concentration_target: Optional["Entity"] = None
    # Concentration as a first-class lifetime (§4.2): the scope owns the revoke
    # handles for everything the concentrated spell granted. Coexists with the
    # legacy string fields above — new-engine spells use the scope, legacy spells
    # the strings; begin_concentration disposes whichever is present.
    concentration_scope: Optional[LifetimeScope] = None
    # Non-concentration lifetime scopes held by this entity (durations). No clock
    # ticks them down yet; they carry their revoke handles for future teardown.
    lifetimes: List[LifetimeScope] = field(default_factory=list)
    active_effects: dict = field(default_factory=dict)  # {trigger_str: [Rule, ...]}
    stat_modifiers: List[StatModifier] = field(default_factory=list)
    granted_actions: List[Action] = field(default_factory=list)  # Temporary actions from effects
    resources: Optional[ActionResources] = None
    spell_slots: Optional[SpellSlots] = None
    legendary_actions: Optional[LegendaryActions] = None
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __post_init__(self) -> None:
        """Validate entity and initialize mutable state."""
        if not self.stat_block:
            raise ValueError("Entity must have a stat block")
        if self.current_hp is None:
            self.current_hp = self.stat_block.hit_points_max
        if self.resources is None:
            defaults = self.stat_block.resource_defaults
            self.resources = ActionResources(
                actions=defaults.get("actions", 1),
                bonus_actions=defaults.get("bonus_actions", 1),
                reactions=defaults.get("reactions", 1),
                movement=defaults.get("speed", 30),
            )
        if self.spell_slots is None and self.stat_block.spell_slot_defaults:
            self.spell_slots = SpellSlots.from_dict(self.stat_block.spell_slot_defaults)
        if self.legendary_actions is None and self.stat_block.legendary_action_count > 0:
            self.legendary_actions = LegendaryActions(
                count_per_round=self.stat_block.legendary_action_count
            )

    def __hash__(self) -> int:
        return hash(self.entity_id)

    def __eq__(self, other) -> bool:
        if isinstance(other, Entity):
            return self.entity_id == other.entity_id
        return False

    # ------------------------------------------------------------------
    # HP management
    # ------------------------------------------------------------------

    def take_damage(self, damage: Damage) -> int:
        """Reduce hit points and return remaining HP.

        Temporary hit points absorb damage first.  Any excess carries
        over to regular hit points (PHB temp-HP rules).
        """
        remaining = damage.amount
        if self.temporary_hp > 0:
            absorbed = min(self.temporary_hp, remaining)
            self.temporary_hp -= absorbed
            remaining -= absorbed
        self.current_hp = max(0, self.current_hp - remaining)
        return self.current_hp

    def heal(self, amount: int) -> int:
        """Increase hit points, capped at maximum."""
        self.current_hp = min(self.stat_block.hit_points_max, self.current_hp + amount)
        return self.current_hp

    def add_temporary_hp(self, amount: int) -> RevokeHandle:
        """Grant temporary hit points; return a handle that revokes this grant.

        Per D&D rules, temp HP don't stack — the entity keeps whichever value is
        higher (current temp HP or the new amount). The returned handle removes
        this grant's contribution when disposed (best-effort: it restores the
        pre-grant value, since a spell's temp HP ends with the spell). Used by a
        lifetime scope; direct callers may ignore the return.
        """
        prior = self.temporary_hp
        if amount > 0:
            self.temporary_hp = max(self.temporary_hp, amount)

        def _revoke() -> None:
            # Only strip what may still be ours: if temp HP hasn't dropped below
            # the pre-grant value, restore it; if damage ate into it, leave it —
            # there is nothing of this grant left to remove.
            if self.temporary_hp > prior:
                self.temporary_hp = prior

        return RevokeHandle(_revoke, label="temp_hp")

    def clear_temporary_hp(self) -> None:
        """Remove all temporary hit points."""
        self.temporary_hp = 0

    def is_alive(self) -> bool:
        """Check if entity is conscious and able to act."""
        for c in self.conditions:
            if c.condition_type == ConditionType.UNCONSCIOUS:
                return False
        return self.current_hp > 0

    # ------------------------------------------------------------------
    # Condition management
    # ------------------------------------------------------------------

    def add_condition(self, condition: Condition) -> RevokeHandle:
        """Add a condition; return a handle that removes *this* condition object.

        Removal is by object identity, so a lifetime scope revokes exactly the
        condition it granted even if an identical one was applied elsewhere.
        """
        self.conditions.append(condition)

        def _revoke() -> None:
            self.conditions = [c for c in self.conditions if c is not condition]

        return RevokeHandle(_revoke, label="condition")

    def remove_condition(self, condition_index: int) -> None:
        """Remove a condition by index.

        A condition applied on the block engine owns a lifetime scope (its marker +
        the installed reactive rider); disposing that scope removes the marker via
        its own revoke handle *and* unsubscribes the rider, so the mechanics don't
        leak on dispel. A legacy marker (no scope) is popped directly.
        """
        if not 0 <= condition_index < len(self.conditions):
            return
        condition = self.conditions[condition_index]
        scope = getattr(condition, "owning_scope", None)
        if scope is not None:
            self.lifetimes = [s for s in self.lifetimes if s is not scope]
            scope.dispose()  # revokes the marker handle + the rider (idempotent)
        else:
            self.conditions.pop(condition_index)

    def get_active_conditions(self) -> List[Condition]:
        """Get all non-expired conditions."""
        return self.conditions.copy()

    def remove_condition_by_type(self, condition_type: ConditionType) -> None:
        """Remove all conditions of the given type."""
        self.conditions = [c for c in self.conditions if c.condition_type != condition_type]

    # ------------------------------------------------------------------
    # Effect management (for rule engine)
    # ------------------------------------------------------------------

    def add_effect(self, trigger: str, effect) -> None:
        """Add an effect to the trigger bucket."""
        self.active_effects.setdefault(trigger, []).append(effect)

    def remove_effect(self, name: str) -> None:
        """Remove all effects matching this name.

        Handles both engines: a block-installed rider is owned by a
        :class:`LifetimeScope` on ``lifetimes`` keyed to the effect name — disposing
        it unsubscribes the rider and revokes its grants by identity. A legacy effect
        is a string-tagged entry, so any :class:`StatModifier`, granted action, and
        :class:`Condition` carrying this name is stripped too.
        """
        scopes = [s for s in self.lifetimes if s.source == name]
        if scopes:
            for scope in scopes:
                scope.dispose()
            self.lifetimes = [s for s in self.lifetimes if s.source != name]
        for bucket in self.active_effects.values():
            bucket[:] = [e for e in bucket if e.name != name]
        self.stat_modifiers = [m for m in self.stat_modifiers if m.effect_name != name]
        self.granted_actions = [a for a in self.granted_actions if a.source_effect != name]
        self.conditions = [c for c in self.conditions if c.effect_name != name]

    def grant_action(self, action: Action) -> RevokeHandle:
        """Attach a temporary action; return a handle that removes *this* action.

        Removal is by object identity, so a lifetime scope revokes exactly the
        action it granted.
        """
        self.granted_actions.append(action)

        def _revoke() -> None:
            self.granted_actions = [a for a in self.granted_actions if a is not action]

        return RevokeHandle(_revoke, label="granted_action")

    def get_effects_for_trigger(self, trigger: str) -> list:
        """Get all effects for a given trigger string."""
        return self.active_effects.get(trigger, [])

    def add_stat_modifier(self, mod: StatModifier) -> RevokeHandle:
        """Attach a stat modifier; return a handle that removes *this* modifier.

        Removal is by object identity, so two modifiers sharing a source/name
        revoke independently (the string-tag cleanup could over-remove both).
        """
        self.stat_modifiers.append(mod)

        def _revoke() -> None:
            self.stat_modifiers = [m for m in self.stat_modifiers if m is not mod]

        return RevokeHandle(_revoke, label="modifier")

    def get_stat_modifiers(self, stat: str) -> List[StatModifier]:
        """Return all modifiers for a given stat key."""
        return [m for m in self.stat_modifiers if m.stat == stat]

    def get_stat_breakdown(self, stat: str) -> List[dict]:
        """Return a breakdown list for display, starting with the base value.

        Each entry is ``{"source": str, "value": int}``.  The first entry is
        always the base value from the stat block (e.g. the flat armor_class).
        Subsequent entries are the :class:`StatModifier` objects for that stat.

        Currently supported base stats: ``"ac"``.  For other stat keys the
        base value will be 0 with label ``"Base"``; callers can supply the
        correct base when building the breakdown themselves.
        """
        _sc_ability = self.stat_block.spellcasting_ability
        _sc_mod = self.get_ability_modifier(_sc_ability) if _sc_ability else 0
        base_map = {
            "ac": self.stat_block.armor_class,
            "spell_save_dc": 8 + self.stat_block.proficiency_bonus + _sc_mod,
            "spell_attack_bonus": self.stat_block.proficiency_bonus + _sc_mod,
        }
        breakdown = [{"source": "Base", "value": base_map.get(stat, 0)}]
        breakdown += [{"source": m.source, "value": m.value}
                      for m in self.stat_modifiers if m.stat == stat]
        return breakdown

    # ------------------------------------------------------------------
    # Resource management (action economy)
    # ------------------------------------------------------------------

    def can_afford(self, cost: ActionCost) -> bool:
        """Check whether the entity can pay *cost*."""
        return self.resources.can_afford(cost)

    def spend_resources(self, cost: ActionCost) -> None:
        """Deduct *cost* from current resources."""
        self.resources.spend(cost)

    def refill_resources(self) -> None:
        """Reset resources to stat block defaults."""
        defaults = self.stat_block.resource_defaults
        self.resources.actions = defaults.get("actions", 1)
        self.resources.bonus_actions = defaults.get("bonus_actions", 1)
        self.resources.reactions = defaults.get("reactions", 1)
        self.resources.movement = defaults.get("speed", 30)

    def add_resource(self, resource_name: str, amount: int) -> None:
        """Add bonus resources (can exceed defaults)."""
        current = getattr(self.resources, resource_name)
        setattr(self.resources, resource_name, current + amount)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def has_concentration(self) -> bool:
        return self.concentrating_on is not None or self.concentration_scope is not None

    # ------------------------------------------------------------------
    # Concentration as a first-class lifetime (§4.2)
    # ------------------------------------------------------------------

    def begin_concentration(
        self, scope: LifetimeScope, *, target: Optional["Entity"] = None
    ) -> None:
        """Start concentrating on *scope*, dropping any prior concentration first.

        Disposes the previous concentration atomically — a new-engine ``scope`` or
        a legacy string-tagged effect — so its entire granted subtree is gone
        before the new one takes hold (design §6.3). The new spell's grants are
        expected to have registered their revoke handles into *scope* already.

        The legacy ``concentrating_on`` / ``concentration_target`` fields are
        mirrored (from the scope's ``source`` and *target*) so consumers that read
        them see consistent state during the transition; the scope stays
        authoritative for teardown.
        """
        self._dispose_current_concentration()
        self.concentration_scope = scope
        self.concentrating_on = scope.source or None
        self.concentration_target = target

    def end_concentration(self) -> None:
        """Drop concentration and revoke everything the concentrated spell granted.

        Disposes the owned scope (identity-based teardown) and cleans up any
        legacy string-tagged grant, then clears all concentration state. The
        single entry point the break rule (and death) should call.
        """
        self._dispose_current_concentration()

    def tick_lifetimes(self) -> None:
        """Count down this entity's timed lifetime scopes; dispose the expired.

        Called on the entity's ``TURN_END`` (the duration clock). A concentration
        scope that runs out ends concentration; a duration scope that runs out (or
        has already self-disposed) is dropped. Scopes with no timer are untouched.
        """
        if self.concentration_scope is not None and self.concentration_scope.tick():
            self.end_concentration()
        surviving: List[LifetimeScope] = []
        for scope in self.lifetimes:
            if scope.tick():
                scope.dispose()
            elif not scope.disposed:
                surviving.append(scope)
        self.lifetimes = surviving

    def _dispose_current_concentration(self) -> None:
        if self.concentration_scope is not None:
            # The scope is authoritative — identity teardown of all it granted.
            # (The string fields are only display mirrors here, so no string-tag
            # cleanup; just clear them below.)
            self.concentration_scope.dispose()
            self.concentration_scope = None
        elif self.concentrating_on and self.concentration_target is not None:
            # Pure legacy string-tag concentration (no scope).
            self.concentration_target.remove_effect(self.concentrating_on)
        self.concentrating_on = None
        self.concentration_target = None

    @property
    def name(self) -> str:
        return self.stat_block.name

    @property
    def hp(self) -> int:
        return self.current_hp

    @property
    def max_hp(self) -> int:
        return self.stat_block.hit_points_max

    def get_ability_modifier(self, ability: str) -> int:
        """Return the ability modifier for the given ability score."""
        return self.stat_block.ability_scores.get_modifier(ability)

    @property
    def ac(self) -> int:
        return self.stat_block.armor_class + sum(
            m.value for m in self.stat_modifiers if m.stat == "ac"
        )

    @property
    def spell_save_dc(self) -> int:
        """Computed spell save DC: 8 + proficiency + spellcasting ability mod + bonuses."""
        ability = self.stat_block.spellcasting_ability
        base_mod = self.get_ability_modifier(ability) if ability else 0
        base = 8 + self.stat_block.proficiency_bonus + base_mod
        return base + sum(m.value for m in self.stat_modifiers if m.stat == "spell_save_dc")

    @property
    def spell_attack_bonus(self) -> int:
        """Computed spell attack bonus: proficiency + spellcasting ability mod + bonuses."""
        ability = self.stat_block.spellcasting_ability
        base_mod = self.get_ability_modifier(ability) if ability else 0
        base = self.stat_block.proficiency_bonus + base_mod
        return base + sum(m.value for m in self.stat_modifiers if m.stat == "spell_attack_bonus")

    @property
    def spellcasting_modifier(self) -> int:
        """Raw ability modifier for the entity's spellcasting ability, or 0 if non-caster."""
        ability = self.stat_block.spellcasting_ability
        return self.get_ability_modifier(ability) if ability else 0

    @property
    def bounding_box(self):
        """Axis-aligned bounding box for this entity based on position and size.

        The entity's (x, y, z) position is the *centre* of its footprint on
        the ground plane.  X and Z are centred on the position; Y is the
        ground elevation (the box extends upward by ``size_ft`` from ``y``).

        This matches the frontend convention where a token's coordinate is
        its visual centre.

        Returns:
            BoundingBox: The AABB representing this entity's occupied space.
        """
        from src.spatial.geometry import BoundingBox, Point3D
        s = self.stat_block.size.size_ft
        half = s / 2.0
        return BoundingBox(
            min_corner=Point3D(self.x - half, self.y, self.z - half),
            max_corner=Point3D(self.x + half, self.y + s, self.z + half),
        )
