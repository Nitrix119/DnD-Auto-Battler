"""Stat modifier — a labeled bonus/penalty on a composite stat."""

from dataclasses import dataclass


@dataclass
class StatModifier:
    """A single labeled contribution to a composite stat.

    The ``stat`` field is an open string namespace; any value is valid.
    Convention for built-in stats:
        "ac"                       — Armor Class
        "saving_throw.<ability>"   — saving throw for a specific ability (e.g. "saving_throw.wisdom")
        "saving_throw.all"         — applies to all saving throws
        "spell_attack_bonus"       — spell attack roll bonus
        "spell_save_dc"            — spell save DC bonus
        "max_hp"                   — maximum hit point bonus

    Attributes:
        stat:        The stat this modifier applies to (open namespace).
        value:       Flat integer bonus (negative values are penalties).
        source:      Human-readable label displayed in breakdown tooltips.
        effect_name: The named effect that owns this modifier.  Used by
                     ``Entity.remove_effect`` to clean up modifiers
                     automatically when the effect expires.
    """

    stat: str
    value: int
    source: str
    effect_name: str
