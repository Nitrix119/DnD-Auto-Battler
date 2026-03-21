import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from src.combat.combat_system import CombatSystem

router = APIRouter()

_CREATURES_DIR = Path(__file__).parent.parent.parent / "examples" / "creatures"
_SPELLS_DIR    = Path(__file__).parent.parent.parent / "examples" / "spells"


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
    # Guard against path traversal
    if not str(creature_path).startswith(str(_CREATURES_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not creature_path.exists():
        raise HTTPException(status_code=404, detail="Creature not found")
    with creature_path.open() as f:
        return json.load(f)


@router.get("/api/spells/by-name/{name}")
async def get_spell_by_name(name: str) -> dict:
    """Find and return a spell JSON by matching its 'name' field (case-insensitive)."""
    for path in sorted(_SPELLS_DIR.rglob("*.json")):
        with path.open() as f:
            data = json.load(f)
        if data.get("name", "").lower() == name.lower():
            return data
    raise HTTPException(status_code=404, detail="Spell not found")


@router.websocket("/ws/combat")
async def combat_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    combat = CombatSystem()  # one CombatSystem instance per connection
    try:
        await websocket.send_json({
            "type": "connected",
            "state": combat.state.name,  # "SETUP"
        })
        while True:
            await websocket.receive_json()  # keep-alive; future commands dispatched here
    except WebSocketDisconnect:
        pass  # combat goes out of scope → garbage collected
