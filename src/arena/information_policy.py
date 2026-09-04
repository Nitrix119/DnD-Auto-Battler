"""What an agent is allowed to know about its enemies.

The :class:`InformationPolicy` is the arena's experiment knob. An observation of
the battle always shows an agent its own entity and its allies in full; each
*enemy* is passed through the policy first, which can hide or coarsen facts such
as exact HP or AC. Because the policy is the only thing that shapes the enemy
view, an experiment ("how does hiding enemy HP change play?") is a one-line
policy change plus a batch run — no engine edits.

Position is never hidden in v1: the engine needs it for range and overlap
checks, and both agents can see the battlefield. A future "fog of war" is a
larger, separate design (see ``docs/AGENT_ARENA_PLAN.md`` §10).
"""

from dataclasses import dataclass


# HP display modes for enemies.
HP_EXACT = "exact"  # numeric current/max/temp HP
HP_BUCKETED = "bucketed"  # a coarse label: "healthy" / "bloodied" / "critical"
HP_HIDDEN = "hidden"  # no HP information at all

_HP_MODES = frozenset({HP_EXACT, HP_BUCKETED, HP_HIDDEN})


@dataclass(frozen=True)
class InformationPolicy:
    """Toggles controlling what an agent learns about *enemy* entities.

    Attributes:
        reveal_enemy_hp: When False, no HP is shown regardless of ``hp_display``.
        hp_display: How HP is shown when revealed — ``"exact"``, ``"bucketed"``
            (a coarse label), or ``"hidden"`` (equivalent to ``reveal_enemy_hp``
            being False).
        reveal_enemy_ac: Show each enemy's armor class.
        reveal_enemy_resources: Show each enemy's action-economy budget.
        reveal_enemy_conditions: Show the conditions currently on each enemy.
        reveal_enemy_spell_slots: Show each enemy's remaining spell slots.
        reveal_enemy_actions: Show each enemy's capabilities (attacks and known spells).
            Hidden-by-default in the info-asymmetry experiments — realistically you learn
            an enemy's abilities by seeing them used, not from a stat sheet (A3).
    """

    reveal_enemy_hp: bool = True
    hp_display: str = HP_EXACT
    reveal_enemy_ac: bool = True
    reveal_enemy_resources: bool = True
    reveal_enemy_conditions: bool = True
    reveal_enemy_spell_slots: bool = True
    reveal_enemy_actions: bool = True

    def __post_init__(self) -> None:
        if self.hp_display not in _HP_MODES:
            raise ValueError(
                f"hp_display must be one of {sorted(_HP_MODES)}, "
                f"got {self.hp_display!r}"
            )

    @property
    def shows_hp(self) -> bool:
        """True when any HP information reaches the agent."""
        return self.reveal_enemy_hp and self.hp_display != HP_HIDDEN


#: The milestone-1 default: enemies are fully visible. Constructing a stricter
#: policy is how experiments opt into hidden information.
FULL_INFORMATION = InformationPolicy()


def bucket_hp(current_hp: int, max_hp: int) -> str:
    """Return a coarse health label for *current_hp* out of *max_hp*.

    ``"critical"`` at or below a quarter, ``"bloodied"`` at or below half,
    ``"healthy"`` above half. Used for :data:`HP_BUCKETED` display so an agent
    learns roughly how hurt an enemy is without an exact number.
    """
    if max_hp <= 0:
        return "critical"
    fraction = current_hp / max_hp
    if fraction <= 0.25:
        return "critical"
    if fraction <= 0.5:
        return "bloodied"
    return "healthy"
