"""Build a match-ready ``CombatSystem`` — the arena's single combat-setup path.

Combat needs more than combatants: the **global rules** in ``rules/global/`` (the per-turn
action-economy refill, critical hit/miss, and damage resistance/immunity/vulnerability)
must be installed on the event bus or turns don't refill and fights stalemate. The web
layer does this in its ``start_combat`` handler; :func:`build_combat` is the arena's mirror,
so no arena caller has to remember the wiring (the kind of silent seam CLAUDE.md §4 warns
about).
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Optional

from src.combat.combat_system import CombatSystem
from src.models.entity import Entity
from src.spells.rules import load_rules_from_directory

if TYPE_CHECKING:
    from src.combat.spell_registry import SpellRegistry

_GLOBAL_RULES_DIR = Path(__file__).resolve().parents[2] / "rules" / "global"


def install_global_rules(combat: CombatSystem) -> None:
    """Install the global rules (per-turn refill, crits, damage modifiers) on *combat*.

    Loads each JSON rule under ``rules/global/`` onto the combat's event bus, exactly as
    the web layer does. Install once per combat — installing twice double-subscribes.
    """
    load_rules_from_directory(
        str(_GLOBAL_RULES_DIR),
        event_bus=combat.event_bus,
        damage_processor=combat._damage_processor,
    )


def build_combat(
    entities: Iterable[Entity],
    *,
    spell_registry: Optional["SpellRegistry"] = None,
    condition_rules: Any = None,
    global_rules: bool = True,
) -> CombatSystem:
    """Assemble an unstarted, match-ready :class:`CombatSystem`.

    Args:
        entities: The combatants to add (already positioned, on their teams).
        spell_registry: Registry used to resolve ``known_spells`` at cast time.
        condition_rules: The effect registry the ``apply_condition`` block reads
            (needed for condition-applying spells).
        global_rules: Install the ``rules/global/`` set (default True). Turn it off only
            for a deliberately bare combat — without it, resources never refill.
    """
    combat = CombatSystem()
    for entity in entities:
        combat.add_combatant(entity)
    if spell_registry is not None:
        combat.spell_registry = spell_registry
    if condition_rules is not None:
        combat.condition_rules = condition_rules
    if global_rules:
        install_global_rules(combat)
    return combat
