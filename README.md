# D&D Auto-Battler

A Python-based D&D 5e combat simulator with a browser-based UI, WebSocket-driven live combat, and a fully data-driven creature and spell system. Every creature, spell, and rule is defined in JSON — no code changes required to add new content.

---

## Features

- **Full D&D 5e Combat**: Initiative tracking, turn order, and a complete action economy (actions, bonus actions, reactions, movement speed).
- **Weapon Attacks**: Hit rolls against AC with typed damage formulas (e.g. `"1d8+3"` slashing).
- **Spell Effects Pipeline**: A sequential step-based pipeline handling attack rolls, saving throws, damage, healing, temporary HP, stat modifiers, status conditions, and persistent entity effects.
- **Area-of-Effect Spells**: Spatial geometry engine enforces AoE shapes (sphere, cone, line, cylinder, cube) and auto-selects targets inside the blast.
- **Legendary Actions**: Creatures can spend legendary action points outside their normal turn.
- **Damage Modifiers**: Per-creature vulnerability, resistance, and immunity to all 5e damage types, enforced by the global rule engine.
- **Entity Effects and Conditions**: Concentration tracking, buff/debuff effects that add modifiers or grant additional actions, and status conditions with durations.
- **Data-Driven Content**: Creatures, spells, and rules are JSON files — add or modify content without touching Python.
- **Web UI with Live Combat**: FastAPI backend with WebSocket sessions drives a canvas-based front-end. Combat state is streamed to the browser in real time.
- **Spell Animations**: A declarative JSON animation system controls canvas visual effects (projectiles, expanding rings, cones, beams, particles, flashes, auras) without any JavaScript changes.

---

## Project Structure

```
src/
├── models/          # Core data structures: StatBlock, Entity, Action, Condition, SpellSlots, etc.
├── combat/          # Combat simulation: CombatSystem, TurnManager, AttackResolver,
│                    #   SpellResolver, EffectPipeline, EventBus, InitiativeTracker
├── loaders/         # JSON stat block loading and deserialization (StatBlockLoader)
├── rules/           # Rule engine, entity effects, expressions sandbox
├── spatial/         # AoE geometry, range checking, 3D grid math
└── utils/           # Dice roller, saving throw helpers

web/
├── app.py           # FastAPI application factory; mounts spell and effect registries
├── routers/
│   ├── combat.py    # HTTP creature/spell endpoints and WebSocket combat session
│   └── health.py    # Health check endpoint
└── static/js/       # Browser-side combat client
    ├── battle.js    # Combat orchestration and WebSocket message handling
    ├── animation.js # Canvas animation engine (data-driven from spell JSON)
    ├── renderer.js  # Grid and token rendering
    └── state.js     # Shared client state

examples/
├── creatures/       # Creature and character JSON stat blocks
└── spells/          # Spell JSON definitions (auto-registered at startup)

rules/
├── global/          # Global combat rules (damage modifier enforcement, etc.)
└── entity_effects/  # Named persistent effects (haste, charmed, shield_of_faith, etc.)

tests/               # pytest suite covering combat, spells, spatial, rules, and the web layer
```

---

## Defining Content

All creatures, spells, and animations are defined in JSON. Three reference guides cover the full format:

| Guide | What it covers |
|---|---|
| [Creature Definition Guide](examples/creatures/CREATURE_DEFINITION_GUIDE.md) | Stat blocks, ability scores, saving throws, actions, spellcasting, legendary actions, damage modifiers, resource defaults |
| [Spell & Action Definition Guide](examples/spells/SPELL_DEFINITION_GUIDE.md) | Weapon attacks, spell top-level fields, the full effects pipeline (`attack_roll`, `saving_throw`, `damage`, `healing`, `add_entity_effect`, `apply_condition`, `add_modifier`, `grant_temporary_hp`), and the expression sandbox |
| [Animation Guide](examples/spells/ANIMATION_GUIDE.md) | Phase/effect structure, all seven canvas effect types (`projectile`, `expanding_ring`, `expanding_cone`, `flash`, `aura`, `particles`, `beam`), location references, and ready-made recipes by spell pattern |

### Quick example — loading a creature in Python

```python
from src.loaders import StatBlockLoader
from src.models import Entity
from src.combat import CombatSystem

goblin_block = StatBlockLoader.load_from_json("examples/creatures/goblin.json")
wizard_block = StatBlockLoader.load_from_json("examples/creatures/characters/wizard.json")

goblin = Entity(goblin_block)
wizard = Entity(wizard_block, is_player_controlled=True, team="players")

combat = CombatSystem()
combat.add_combatant(goblin)
combat.add_combatant(wizard)
combat.start_combat()
```

Spells listed in `known_spells` are resolved from the spell registry, which is populated at startup by scanning `examples/spells/`. Spell actions can also be embedded directly in a creature's `"actions"` array.

---

## Installation

```bash
# Core library only
pip install -e .

# With web server and dev tools
pip install -e ".[web,dev]"
```

Requires Python 3.9+.

---

## Running the Web UI

```bash
uvicorn web.app:app --reload
```

Or on Windows:

```bat
serve.bat
```

Then open `http://localhost:8000` in a browser. The front-end connects over WebSocket and streams live combat events as they are resolved.

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Architecture Notes

- **Event bus**: Combat actions publish typed events (`ATTACK_DECLARED`, `DAMAGE_DEALT`, `CONDITION_APPLIED`, etc.) through a central `EventBus`. Entity effects and global rules subscribe to events and can intercept or modify them before resolution.
- **Effects pipeline**: Each spell carries a sequential list of pipeline steps. Steps share an ephemeral context dictionary — earlier steps (e.g. `attack_roll`) write values (`context.hit`, `context.damage_dealt`) that later steps (e.g. `damage`, `healing`) can read and branch on.
- **Expression sandbox**: Conditional and computed fields in the pipeline accept sandboxed Python expression strings evaluated at runtime. These have access to `event.caster`, `event.defender`, and the pipeline `context`, but disallow assignments, imports, and any access to private attributes.
- **Rule engine**: Global rules (e.g. damage modifiers) and named entity effects (e.g. `haste`, `charmed`) are loaded from JSON at startup and applied by a `RuleEngine` that holds a handler registry. Handlers are keyed by action type (`AddModifier`, `ApplyCondition`, `GrantAction`, etc.).

---

## Future Goals

- **LLM-powered creature action selection**: Rather than using a simple heuristic, the combat engine will call an LLM at each non-player turn to decide which action a creature takes. The model will receive the current combat state — the acting creature's available actions, the positions and condition of all combatants, remaining resources — and return a structured action choice. This brings emergent, tactically interesting behaviour to monster turns without hand-scripted AI trees.
- Spell slot upcasting with structured higher-level scaling (damage riders per slot level above base).
- Multiattack — spending one action to make several attack rolls.
- Reaction support (e.g. Shield, Opportunity Attack) triggered by event bus hooks.
- Party vs. party matchmaking with configurable team compositions.
- Equipment and magic item stat modifiers.
- YAML alternative to JSON for stat blocks.

---

## License

No license is granted at this time. All rights reserved.

This project is actively being developed and is not yet open for general use, modification, or redistribution. The intent is to release it under an open source license once it reaches a more complete state.
