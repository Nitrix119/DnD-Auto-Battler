from enum import Enum


class EventType(Enum):
    # Turn lifecycle
    ROUND_START = "round_start"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    ROUND_END = "round_end"

    # Attack flow
    ATTACK_DECLARED = "attack_declared"  # before roll; can be cancelled
    ATTACK_ROLLED = "attack_rolled" # after rolling to hit, before evaluating hit/miss
    ATTACK_HIT = "attack_hit"
    ATTACK_MISS = "attack_miss"

    # Spell flow
    SPELL_CAST = "spell_cast"
    SPELL_HIT = "spell_hit"

    # Saving throw flow
    SAVING_THROW_DECLARED = "saving_throw_declared"  # before roll; handlers can set advantage/disadvantage

    # Damage flow
    DAMAGE_INCOMING = "damage_incoming"  # before HP reduction; handlers can modify damage
    DAMAGE_DEALT = "damage_dealt"  # after damage is applied to the target

    # Healing flow
    HEALING_APPLIED = "healing_applied"  # after HP is restored

    # Entity lifecycle
    ENTITY_DIES = "entity_dies"
    CONDITION_ADDED = "condition_added"
    CONDITION_REMOVED = "condition_removed"
