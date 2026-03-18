import json
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.combat.combat_system import CombatSystem

router = APIRouter()

_CREATURES_DIR = Path(__file__).parent.parent.parent / "examples" / "creatures"


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
