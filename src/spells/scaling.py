"""Slot-based damage scaling — the one shared helper for upcasting a formula.

Upcasting is a declared modifier, not an author-written expression: a damage block's
``scaling`` object ``{"per_slot_above": N, "add_dice": "1d6"}`` adds
``(slot_level - N)`` copies of ``add_dice`` to the base formula when the spell is
cast with a slot above ``N``. The result is a plain dice-formula string, so
crit-doubling and the ``roll_once`` pre-roll keep working over it unchanged.

Used by the ``damage`` block and the ``for_each_target`` iterator's shared pre-roll.
(Formerly lived in the legacy ``effect_pipeline`` module; it moved here when that
engine was retired.)
"""

from __future__ import annotations

from typing import Optional

from src.utils.dice import multiply_formula


def effective_damage_formula(block: dict, slot_level: Optional[int]) -> str:
    """Return a damage block's formula with any slot-based ``scaling`` applied."""
    formula = block.get("formula", "")
    scaling = block.get("scaling")
    if not scaling or not formula or slot_level is None:
        return formula
    per_slot_above = scaling.get("per_slot_above")
    add_dice = scaling.get("add_dice")
    if per_slot_above is None or not add_dice:
        return formula
    extra_levels = int(slot_level) - int(per_slot_above)
    if extra_levels <= 0:
        return formula
    return f"{formula}+{multiply_formula(add_dice, extra_levels)}"
