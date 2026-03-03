from enum import Enum


class EventType(Enum):
    # Turn lifecycle
    ROUND_START = "round_start"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    ROUND_END = "round_end"

    # Attack flow
    ATTACK_DECLARED = "attack_declared"  # before roll; can be cancelled
    ATTACK_HIT = "attack_hit"
    ATTACK_MISS = "attack_miss"

    # Spell flow
    SPELL_CAST = "spell_cast"
    SPELL_HIT = "spell_hit"

    # Damage flow
    DAMAGE_DEALT = "damage_dealt"  # after damage is applied to the target

    # Entity lifecycle
    ENTITY_DIES = "entity_dies"
    CONDITION_ADDED = "condition_added"
    CONDITION_REMOVED = "condition_removed"
