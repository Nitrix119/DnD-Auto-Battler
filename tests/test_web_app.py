"""Tests for the FastAPI web application, spell endpoint, and WebSocket combat session.

These tests verify that the web layer (FastAPI + WebSocket) is properly
installed and wired up.  They require ``httpx`` (for the Starlette test
client) in addition to ``fastapi`` and ``uvicorn``.
"""

import pytest
from starlette.testclient import TestClient

from web.app import create_app


@pytest.fixture()
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# App creation & SpellRegistry
# ---------------------------------------------------------------------------

class TestAppCreation:
    def test_app_creates_successfully(self):
        app = create_app()
        assert app.title == "D&D Auto Battler"

    def test_spell_registry_loaded(self):
        app = create_app()
        registry = app.state.spell_registry
        assert len(registry) > 0

    def test_spell_registry_contains_known_spells(self):
        app = create_app()
        registry = app.state.spell_registry
        assert "Fireball" in registry
        assert "Fire Bolt" in registry
        assert "Haste" in registry


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

class TestCreatureEndpoints:
    def test_list_creatures(self, client):
        r = client.get("/api/creatures")
        assert r.status_code == 200
        creatures = r.json()
        assert isinstance(creatures, list)
        assert len(creatures) > 0
        assert all("name" in c and "path" in c for c in creatures)

    def test_get_creature_by_path(self, client):
        # First get the list, then fetch one
        creatures = client.get("/api/creatures").json()
        first = creatures[0]
        r = client.get(f"/api/creatures/{first['path']}")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == first["name"]

    def test_get_creature_not_found(self, client):
        r = client.get("/api/creatures/nonexistent.json")
        assert r.status_code == 404


class TestSpellEndpoint:
    def test_get_spell_by_name(self, client):
        r = client.get("/api/spells/by-name/Fireball")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Fireball"
        assert data["spell_level"] == 3
        assert data["spell_range"]["type"] == "feet"

    def test_get_spell_case_insensitive(self, client):
        r = client.get("/api/spells/by-name/fire bolt")
        assert r.status_code == 200
        assert r.json()["name"] == "Fire Bolt"

    def test_get_spell_not_found(self, client):
        r = client.get("/api/spells/by-name/Wish")
        assert r.status_code == 404

    def test_spell_uses_registry_not_filesystem(self, client):
        """Verify the endpoint returns serialized SpellAction data (has 'cost' key
        from _serialize_action), not raw JSON (which uses 'casting_time' but no 'cost')."""
        r = client.get("/api/spells/by-name/Fireball")
        data = r.json()
        # _serialize_action always includes 'casting_time' and 'duration'
        assert "casting_time" in data
        assert "duration" in data
        assert "targeting_type" in data


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

class TestWebSocketCombat:
    def test_connect_receives_connected_message(self, client):
        with client.websocket_connect("/ws/combat") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "connected"
            assert msg["state"] == "SETUP"

    def test_unknown_command_returns_error(self, client):
        with client.websocket_connect("/ws/combat") as ws:
            ws.receive_json()  # consume "connected"
            ws.send_json({"type": "bogus", "seq": 1})
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert msg["seq"] == 1
            assert "Unknown command" in msg["message"]

    def test_start_combat(self, client):
        with client.websocket_connect("/ws/combat") as ws:
            ws.receive_json()  # consume "connected"
            ws.send_json({
                "type": "start_combat",
                "seq": 1,
                "combatants": [
                    {
                        "creature_path": "goblin.json",
                        "team": "enemy",
                        "position": {"x": 3, "y": 0},
                        "frontend_id": "fe-1",
                    },
                    {
                        "creature_path": "characters/ranger.json",
                        "team": "ally",
                        "position": {"x": -3, "y": 0},
                        "frontend_id": "fe-2",
                    },
                ],
            })
            msg = ws.receive_json()
            assert msg["type"] == "combat_started"
            assert msg["seq"] == 1

            # ID map should link frontend IDs to backend entity IDs
            assert "fe-1" in msg["id_map"]
            assert "fe-2" in msg["id_map"]

            # Combat state should be ACTIVE with 2 entities
            state = msg["combat_state"]
            assert state["state"] == "ACTIVE"
            assert len(state["entities"]) == 2
            assert state["current_entity_id"] is not None

            # Initiative order should list both combatants
            assert len(msg["initiative_order"]) == 2

    def test_start_combat_positions_converted(self, client):
        """Verify frontend cell coords survive the round-trip through backend feet."""
        with client.websocket_connect("/ws/combat") as ws:
            ws.receive_json()
            ws.send_json({
                "type": "start_combat",
                "seq": 1,
                "combatants": [
                    {
                        "creature_path": "goblin.json",
                        "team": "enemy",
                        "position": {"x": 4.0, "y": 2.0},
                        "frontend_id": "fe-1",
                    },
                    {
                        "creature_path": "characters/ranger.json",
                        "team": "ally",
                        "position": {"x": -3.0, "y": 0.0},
                        "frontend_id": "fe-2",
                    },
                ],
            })
            msg = ws.receive_json()
            entities = {e["name"]: e for e in msg["combat_state"]["entities"]}
            goblin_pos = entities["Goblin"]["position"]
            assert goblin_pos["x"] == pytest.approx(4.0)
            assert goblin_pos["y"] == pytest.approx(2.0)

    def test_end_turn(self, client):
        with client.websocket_connect("/ws/combat") as ws:
            ws.receive_json()
            ws.send_json({
                "type": "start_combat",
                "seq": 1,
                "combatants": [
                    {
                        "creature_path": "goblin.json",
                        "team": "enemy",
                        "position": {"x": 3, "y": 0},
                        "frontend_id": "fe-1",
                    },
                    {
                        "creature_path": "characters/ranger.json",
                        "team": "ally",
                        "position": {"x": -3, "y": 0},
                        "frontend_id": "fe-2",
                    },
                ],
            })
            started = ws.receive_json()
            first_entity = started["combat_state"]["current_entity_id"]

            ws.send_json({"type": "end_turn", "seq": 2})
            msg = ws.receive_json()
            assert msg["type"] == "turn_changed"
            assert msg["seq"] == 2
            # The current entity should have changed
            assert msg["current_entity_id"] != first_entity
