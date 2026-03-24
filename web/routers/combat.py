"""Combat router — HTTP creature/spell endpoints and WebSocket combat session."""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from src.combat.combat_system import CombatSystem
from src.loaders.stat_block_loader import StatBlockLoader
from src.models.action import AttackAction
from src.models.entity import Entity
from src.rules.rule_engine import RuleEngine
from src.spatial.geometry import Point3D

_RULES_DIR = Path(__file__).parent.parent.parent / "rules"

logger = logging.getLogger(__name__)

router = APIRouter()

_CREATURES_DIR = Path(__file__).parent.parent.parent / "examples" / "creatures"

# ---------------------------------------------------------------------------
# Coordinate conversion
# ---------------------------------------------------------------------------
# Frontend: cell units (cx, cy) — x=east, y=south
# Backend:  feet       (x, y, z) — x=east, y=UP, z=south
CELL_FEET = 5


def frontend_to_backend(cx: float, cy: float) -> tuple[float, float, float]:
    """Convert frontend cell coords to backend feet (x, y=0, z)."""
    return (cx * CELL_FEET, 0.0, cy * CELL_FEET)


def backend_to_frontend(entity: Entity) -> dict[str, float]:
    """Convert a backend entity's position to frontend cell coords."""
    return {"x": entity.x / CELL_FEET, "y": entity.z / CELL_FEET}


# ---------------------------------------------------------------------------
# State serialization
# ---------------------------------------------------------------------------

def serialize_combat_state(combat: CombatSystem) -> dict[str, Any]:
    """Build a full combat state snapshot for the frontend."""
    current = combat.get_current_entity()

    # Turn order: entity IDs rotated so the current entity is first
    tracker = combat.initiative_tracker
    if tracker.initiative_order:
        n = len(tracker.initiative_order)
        idx = tracker.current_turn_index
        turn_order = [
            tracker.initiative_order[(idx + i) % n].entity.entity_id
            for i in range(n)
        ]
    else:
        turn_order = []

    return {
        "state": combat.state.name,
        "round": combat.round,
        "turn": combat.turn,
        "current_entity_id": current.entity_id if current else None,
        "turn_order": turn_order,
        "active_entity_ids": list(combat.active_entity_ids),
        "entities": [
            {
                "entity_id": e.entity_id,
                "name": e.name,
                "team": e.team,
                "hp": e.current_hp,
                "max_hp": e.max_hp,
                "temp_hp": e.temporary_hp,
                "ac": e.ac,
                "alive": e.is_alive(),
                "position": backend_to_frontend(e),
                "resources": {
                    "actions": e.resources.actions,
                    "bonus_actions": e.resources.bonus_actions,
                    "reactions": e.resources.reactions,
                    "movement": e.resources.movement,
                },
                "conditions": [c.condition_type.value for c in e.conditions],
                "stat_breakdowns": {
                    "ac": e.get_stat_breakdown("ac"),
                },
            }
            for e in combat.combatants
        ],
    }


def serialize_initiative_order(combat: CombatSystem) -> list[dict[str, Any]]:
    """Return the initiative order with entity IDs and rolls."""
    return [
        {
            "entity_id": e.entity_id,
            "name": e.name,
            "initiative": e.initiative_roll,
        }
        for e in combat.initiative_tracker.get_turn_order()
    ]


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@router.get("/api/creatures")
async def list_creatures() -> list[dict]:
    """Scan examples/creatures/ recursively and return each creature's name and path."""
    creatures = []
    for path in sorted(_CREATURES_DIR.rglob("*.json")):
        with path.open() as f:
            data = json.load(f)
        creatures.append({
            "name": data["name"],
            "path": path.relative_to(_CREATURES_DIR).as_posix(),
        })
    return creatures


@router.get("/api/creatures/{path:path}")
async def get_creature(path: str) -> dict:
    """Return the full JSON for a single creature by relative path."""
    creature_path = (_CREATURES_DIR / path).resolve()
    if not str(creature_path).startswith(str(_CREATURES_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not creature_path.exists():
        raise HTTPException(status_code=404, detail="Creature not found")
    with creature_path.open() as f:
        return json.load(f)


@router.get("/api/spells/by-name/{name}")
async def get_spell_by_name(name: str, request: Request) -> dict:
    """Return spell JSON by name, using the global SpellRegistry."""
    registry = request.app.state.spell_registry
    # Case-insensitive lookup against the registry
    for spell_name in registry._spells:
        if spell_name.lower() == name.lower():
            return StatBlockLoader._serialize_action(registry.get(spell_name))
    raise HTTPException(status_code=404, detail="Spell not found")


# ---------------------------------------------------------------------------
# WebSocket combat session
# ---------------------------------------------------------------------------

async def _send(ws: WebSocket, msg: dict[str, Any]) -> None:
    """Send a JSON message, merging in common fields."""
    await ws.send_json(msg)


async def _send_error(
    ws: WebSocket, seq: int | None, command: str | None, message: str,
) -> None:
    await _send(ws, {
        "type": "error",
        "seq": seq,
        "command": command,
        "message": message,
    })


# ── Handler: start_combat ──────────────────────────────────────────────────

async def handle_start_combat(
    ws: WebSocket,
    combat: CombatSystem,
    msg: dict,
    seq: int | None,
    id_map: dict[str, str],
    entity_lookup: dict[str, Entity],
) -> None:
    combatants_data = msg.get("combatants", [])
    if len(combatants_data) < 2:
        raise ValueError("Need at least 2 combatants to start combat")

    for entry in combatants_data:
        creature_path = (_CREATURES_DIR / entry["creature_path"]).resolve()
        if not str(creature_path).startswith(str(_CREATURES_DIR.resolve())):
            raise ValueError(f"Invalid creature path: {entry['creature_path']}")
        if not creature_path.exists():
            raise ValueError(f"Creature not found: {entry['creature_path']}")

        with creature_path.open() as f:
            creature_data = json.load(f)

        stat_block = StatBlockLoader.from_dict(creature_data)
        entity = Entity(stat_block=stat_block, team=entry.get("team"))

        # Set position from frontend cell coords
        pos = entry.get("position", {"x": 0, "y": 0})
        bx, by, bz = frontend_to_backend(pos["x"], pos["y"])
        entity.x, entity.y, entity.z = bx, by, bz

        # Map frontend ID to backend entity ID
        frontend_id = entry.get("frontend_id", "")
        id_map[frontend_id] = entity.entity_id
        entity_lookup[entity.entity_id] = entity

        combat.add_combatant(entity)

    # Attach global spell registry
    combat.spell_registry = ws.app.state.spell_registry

    # Create per-session rule engine (needs the session's event bus)
    effect_registry = ws.app.state.effect_registry
    rule_engine = RuleEngine(
        combat.event_bus,
        entities_getter=lambda: combat.combatants,
        damage_processor=combat._damage_processor,
        effect_registry=effect_registry,
    )
    rule_engine.load_from_file(str(_RULES_DIR / "concentration.json"))
    rule_engine.load_from_file(str(_RULES_DIR / "action_economy_refill.json"))
    combat.rule_engine = rule_engine

    combat.start_combat()

    await _send(ws, {
        "type": "combat_started",
        "seq": seq,
        "id_map": id_map,
        "initiative_order": serialize_initiative_order(combat),
        "combat_state": serialize_combat_state(combat),
    })


# ── Handler: attack ────────────────────────────────────────────────────────

async def handle_attack(
    ws: WebSocket,
    combat: CombatSystem,
    msg: dict,
    seq: int | None,
    entity_lookup: dict[str, Entity],
) -> None:
    attacker = entity_lookup.get(msg["attacker_id"])
    defender = entity_lookup.get(msg["defender_id"])
    if not attacker or not defender:
        raise ValueError("Unknown attacker or defender entity ID")

    action_name = msg["action_name"]
    action = next(
        (a for a in attacker.stat_block.actions
         if isinstance(a, AttackAction) and a.name == action_name),
        None,
    )
    if action is None:
        raise ValueError(f"{attacker.name} has no attack called '{action_name}'")

    log_before = len(combat.log)
    hit, damage, roll_detail = combat.resolve_attack(attacker, defender, action)
    new_logs = combat.get_combat_log()[log_before:]

    await _send(ws, {
        "type": "action_result",
        "seq": seq,
        "action_type": "attack",
        "attacker_id": attacker.entity_id,
        "results": [
            {"target_id": defender.entity_id, "hit": hit, "damage": damage, "roll": roll_detail},
        ],
        "log": new_logs,
        "combat_state": serialize_combat_state(combat),
    })


# ── Handler: cast_spell ────────────────────────────────────────────────────

async def handle_cast_spell(
    ws: WebSocket,
    combat: CombatSystem,
    msg: dict,
    seq: int | None,
    entity_lookup: dict[str, Entity],
) -> None:
    caster = entity_lookup.get(msg["caster_id"])
    if not caster:
        raise ValueError("Unknown caster entity ID")

    spell_name = msg["spell_name"]
    spell_action = combat.get_spell_for_entity(caster, spell_name)

    # Build target list
    defenders: list[Entity] = []
    for tid in msg.get("target_ids", []):
        ent = entity_lookup.get(tid)
        if ent:
            defenders.append(ent)

    # Convert target point for AoE
    target_point: Point3D | None = None
    tp = msg.get("target_point")
    if tp is not None:
        bx, by, bz = frontend_to_backend(tp["x"], tp["y"])
        target_point = Point3D(bx, by, bz)

    log_before = len(combat.log)
    results = combat.resolve_spell(
        caster, defenders, spell_action, target=target_point,
    )
    new_logs = combat.get_combat_log()[log_before:]

    per_target = [
        {"target_id": entity.entity_id, "hit": hit, "damage": damage, "roll": roll_detail}
        for entity, hit, damage, roll_detail in results
    ]

    await _send(ws, {
        "type": "action_result",
        "seq": seq,
        "action_type": "spell",
        "attacker_id": caster.entity_id,
        "results": per_target,
        "animation": spell_action.animation if spell_action.animation else [],
        "target_point": {"x": tp["x"], "y": tp["y"]} if tp else None,
        "log": new_logs,
        "combat_state": serialize_combat_state(combat),
    })


# ── Handler: move ──────────────────────────────────────────────────────────

async def handle_move(
    ws: WebSocket,
    combat: CombatSystem,
    msg: dict,
    seq: int | None,
    entity_lookup: dict[str, Entity],
) -> None:
    entity = entity_lookup.get(msg["entity_id"])
    if not entity:
        raise ValueError("Unknown entity ID")

    pos = msg["position"]
    bx, by, bz = frontend_to_backend(pos["x"], pos["y"])
    combat.move_entity(entity, bx, by, bz)

    await _send(ws, {
        "type": "move_result",
        "seq": seq,
        "entity_id": entity.entity_id,
        "position": backend_to_frontend(entity),
        "movement_remaining": entity.resources.movement,
        "combat_state": serialize_combat_state(combat),
    })


# ── Handler: end_turn ──────────────────────────────────────────────────────

async def handle_end_turn(
    ws: WebSocket,
    combat: CombatSystem,
    msg: dict,
    seq: int | None,
    entity_lookup: dict[str, Entity],  # noqa: ARG001
) -> None:
    entity_id: str | None = msg.get("entity_id")
    log_before = len(combat.log)
    combat.end_turn(entity_id=entity_id)
    new_logs = combat.get_combat_log()[log_before:]

    if combat.state.name == "ENDED":
        # Determine winning team
        alive = combat.get_alive_entities()
        winner = alive[0].team if alive else None
        await _send(ws, {
            "type": "combat_ended",
            "seq": seq,
            "winner": winner,
            "log": new_logs,
            "combat_state": serialize_combat_state(combat),
        })
    else:
        current = combat.get_current_entity()
        await _send(ws, {
            "type": "turn_changed",
            "seq": seq,
            "round": combat.round,
            "turn": combat.turn,
            "current_entity_id": current.entity_id if current else None,
            "log": new_logs,
            "combat_state": serialize_combat_state(combat),
        })


# ── WebSocket entry point ─────────────────────────────────────────────────

_HANDLERS = {
    "start_combat": handle_start_combat,
    "attack": handle_attack,
    "cast_spell": handle_cast_spell,
    "move": handle_move,
    "end_turn": handle_end_turn,
}


@router.websocket("/ws/combat")
async def combat_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    combat = CombatSystem()

    id_map: dict[str, str] = {}            # frontend_id → entity_id
    entity_lookup: dict[str, Entity] = {}  # entity_id → Entity

    await _send(websocket, {
        "type": "connected",
        "state": combat.state.name,
    })

    try:
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type")
            seq = msg.get("seq")

            handler = _HANDLERS.get(msg_type)
            if handler is None:
                await _send_error(websocket, seq, msg_type, f"Unknown command: {msg_type}")
                continue

            try:
                if handler in (handle_start_combat,):
                    await handler(websocket, combat, msg, seq, id_map, entity_lookup)
                else:
                    await handler(websocket, combat, msg, seq, entity_lookup)
            except (ValueError, RuntimeError, KeyError) as exc:
                logger.warning("Command %s failed: %s", msg_type, exc)
                await _send_error(websocket, seq, msg_type, str(exc))
    except WebSocketDisconnect:
        pass
