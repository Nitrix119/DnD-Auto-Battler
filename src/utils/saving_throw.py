"""Shared saving throw resolution used by spell and combat resolvers."""

from typing import Tuple

from src.utils.dice import roll_d20, roll_with_advantage, roll_with_disadvantage


def roll_saving_throw(
    defender,
    ability: str,
    dc: int,
    *,
    advantage: bool = False,
    disadvantage: bool = False,
) -> Tuple[int, bool]:
    """Roll a saving throw and return (roll_total, success).

    The total includes the base ability/proficiency bonus from the stat block
    plus any :class:`StatModifier` entries on the entity keyed to
    ``"saving_throw.<ability>"`` or the catch-all ``"saving_throw.all"``.

    Args:
        defender: The :class:`Entity` making the save.
        ability: Ability name (e.g. ``"dexterity"``).
        dc: Difficulty class to meet or beat.
        advantage: Roll two d20 and keep the higher (e.g. a Paladin's aura).
        disadvantage: Roll two d20 and keep the lower (e.g. Restrained on a
            Dexterity save).  Per 5e, advantage and disadvantage together
            cancel to a single normal roll.

    Returns:
        ``(total, success)`` where *success* is ``True`` when ``total >= dc``.
    """
    if advantage and not disadvantage:
        roll = roll_with_advantage()
    elif disadvantage and not advantage:
        roll = roll_with_disadvantage()
    else:
        roll = roll_d20()
    base_bonus = defender.stat_block.get_saving_throw_bonus(ability)
    extra = sum(
        m.value for m in defender.stat_modifiers
        if m.stat in (f"saving_throw.{ability.lower()}", "saving_throw.all")
    )
    total = roll + base_bonus + extra
    return total, total >= dc
