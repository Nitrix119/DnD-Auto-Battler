"""Tool schemas and the executor that turns a chosen action into a refereed effect.

This is the arena's **single execution seam** — the mirror of the web layer's
``_HANDLERS`` dispatch. An agent (LLM or scripted) proposes an action as a
:class:`ToolCall`; :class:`ToolExecutor` validates it and dispatches to the existing
``CombatSystem.resolve_attack`` / ``resolve_spell`` / ``move_entity`` / ``end_turn``.
It never resolves combat itself (CLAUDE.md §3, one resolution path) and never mutates
state directly — the engine is the authority. An illegal call is caught and returned as
a structured error the agent can react to, not a crash.

**Provider-neutral (E4).** :data:`TOOLS` are plain JSON-Schema tool definitions in the
``{name, description, input_schema}`` shape. Claude consumes them directly; another
provider's adapter reshapes only the envelope. Positions and points are in **backend
feet** — the engine's own coordinates — matching the observation.

**Resolution transparency (C3).** A success result always states the outcome (hit/miss,
save success, damage) and the acting agent's *own* roll, but the target's defensive
numbers are gated by the actor's :class:`InformationPolicy`: the target's AC (and, for a
save, the target's save-roll value) appear only when ``reveal_enemy_ac`` is set. The
spell **save DC is the actor's own** stat and is always shown; the target's resulting HP
is never in the result (the next observation carries it, gated by ``reveal_enemy_hp``).
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.arena.information_policy import FULL_INFORMATION, InformationPolicy
from src.models.action import AttackAction
from src.models.entity import Entity
from src.spatial.geometry import Point3D

if TYPE_CHECKING:
    from src.combat.combat_system import CombatSystem


# Tool names — the arena's action vocabulary (mirrors the web _HANDLERS commands).
TOOL_ATTACK = "attack"
TOOL_CAST_SPELL = "cast_spell"
TOOL_MOVE = "move"
TOOL_END_TURN = "end_turn"


#: Provider-neutral JSON-Schema tool definitions handed to an agent each turn.
TOOLS: List[Dict[str, Any]] = [
    {
        "name": TOOL_ATTACK,
        "description": (
            "Make a weapon/attack action against one target. Use an attack `name` "
            "and a target `entity_id` from your legal-action menu."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action_name": {
                    "type": "string",
                    "description": "The attack's name, exactly as listed in your options.",
                },
                "defender_id": {
                    "type": "string",
                    "description": "entity_id of the target to attack.",
                },
            },
            "required": ["action_name", "defender_id"],
        },
    },
    {
        "name": TOOL_CAST_SPELL,
        "description": (
            "Cast a spell you know. Single-target/self spells take `target_ids`; "
            "area spells take a `target_point` (in feet) you aim at. Optionally cast at "
            "a higher `slot_level` to upcast."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "spell_name": {
                    "type": "string",
                    "description": "The spell's name, exactly as listed in your options.",
                },
                "target_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "entity_id(s) to target (single-target/self spells).",
                },
                "target_point": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "z": {"type": "number"},
                    },
                    "required": ["x", "y"],
                    "description": "Point in feet to aim an area spell at.",
                },
                "slot_level": {
                    "type": "integer",
                    "description": "Slot level to cast at (>= the spell's base level). "
                    "Omit to cast at its base level.",
                },
            },
            "required": ["spell_name"],
        },
    },
    {
        "name": TOOL_MOVE,
        "description": (
            "Move to a position on the battlefield, in feet. Costs movement equal to the "
            "straight-line distance; you cannot move onto another creature."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "Destination x, in feet (east)."},
                "y": {"type": "number", "description": "Destination y, in feet (up); usually 0."},
                "z": {"type": "number", "description": "Destination z, in feet (south)."},
            },
            "required": ["x", "z"],
        },
    },
    {
        "name": TOOL_END_TURN,
        "description": "End your turn, passing to the next combatant. Take this when done acting.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


@dataclass
class ToolCall:
    """A provider-neutral action proposed by an agent.

    ``name`` is one of the :data:`TOOLS` names; ``arguments`` matches that tool's
    ``input_schema``. ``call_id`` carries a provider's correlation id (e.g. Claude's
    ``tool_use`` block id) when there is one, so the adapter can match the result back.
    """

    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    call_id: Optional[str] = None


def _ok(**fields: Any) -> Dict[str, Any]:
    return {"ok": True, **fields}


def _error(message: str) -> Dict[str, Any]:
    return {"ok": False, "error": message}


def _gate_roll(
    roll_detail: Optional[Dict[str, Any]], policy: InformationPolicy
) -> Optional[Dict[str, Any]]:
    """Reshape a resolver's ``roll_detail`` into an actor-facing roll, gating C3 fields.

    To-hit rolls (carry ``ac``) expose the actor's own d20/bonus/total; the target ``ac``
    only under ``reveal_enemy_ac``. Save rolls (carry ``dc``) expose the actor's own
    ``save_dc`` and the outcome; the target's save-roll value only under
    ``reveal_enemy_ac`` (treated as the target's defensive internals).
    """
    if roll_detail is None:
        return None

    if "ac" in roll_detail:  # attacker/spell-attack to-hit roll
        out: Dict[str, Any] = {"attack_roll": roll_detail["d20"], "attack_total": roll_detail["total"]}
        if "bonus" in roll_detail:
            out["attack_bonus"] = roll_detail["bonus"]
        if policy.reveal_enemy_ac:
            out["target_ac"] = roll_detail["ac"]
        return out

    if "dc" in roll_detail:  # target's saving throw vs the actor's DC
        out = {"save_dc": roll_detail["dc"], "target_saved": roll_detail["save_success"]}
        if policy.reveal_enemy_ac:
            out["target_save_roll"] = roll_detail["total"]
        return out

    return dict(roll_detail)


class ToolExecutor:
    """Validates a :class:`ToolCall` and applies it via the ``CombatSystem`` referee.

    Bound to one combat; :meth:`apply` takes the acting entity and the actor's
    :class:`InformationPolicy` (defaults to :data:`FULL_INFORMATION`), so results are
    shaped from that actor's point of view.
    """

    def __init__(self, combat: "CombatSystem") -> None:
        self._combat = combat

    def apply(
        self,
        actor: Entity,
        call: ToolCall,
        policy: InformationPolicy = FULL_INFORMATION,
    ) -> Dict[str, Any]:
        """Execute *call* for *actor*, returning a structured result or error dict.

        Never raises for an illegal move: an engine ``ValueError`` (wrong turn,
        unaffordable, out of range, no slot, …) or a bad reference becomes
        ``{"ok": False, "error": ...}`` — the self-correction signal.
        """
        handlers = {
            TOOL_ATTACK: self._attack,
            TOOL_CAST_SPELL: self._cast_spell,
            TOOL_MOVE: self._move,
            TOOL_END_TURN: self._end_turn,
        }
        handler = handlers.get(call.name)
        if handler is None:
            return _error(f"Unknown tool: {call.name!r}")
        try:
            return handler(actor, call.arguments, policy)
        except (ValueError, RuntimeError, KeyError) as exc:
            return _error(str(exc))

    # -- individual tools ------------------------------------------------------

    def _lookup(self, entity_id: str) -> Entity:
        for e in self._combat.combatants:
            if e.entity_id == entity_id:
                return e
        raise ValueError(f"Unknown entity_id: {entity_id!r}")

    def _attack(
        self, actor: Entity, args: Dict[str, Any], policy: InformationPolicy
    ) -> Dict[str, Any]:
        action_name = args["action_name"]
        defender = self._lookup(args["defender_id"])
        action = next(
            (
                a
                for a in actor.stat_block.actions + actor.granted_actions
                if isinstance(a, AttackAction) and a.name == action_name
            ),
            None,
        )
        if action is None:
            raise ValueError(f"{actor.name} has no attack called {action_name!r}")

        hit, damage, roll_detail = self._combat.resolve_attack(actor, defender, action)
        return _ok(
            action=TOOL_ATTACK,
            target_id=defender.entity_id,
            hit=hit,
            damage=damage,
            roll=_gate_roll(roll_detail, policy),
        )

    def _cast_spell(
        self, actor: Entity, args: Dict[str, Any], policy: InformationPolicy
    ) -> Dict[str, Any]:
        spell_name = args["spell_name"]
        spell_action = self._combat.get_spell_for_entity(actor, spell_name)

        defenders = [self._lookup(tid) for tid in args.get("target_ids", [])]

        target_point: Optional[Point3D] = None
        tp = args.get("target_point")
        if tp is not None:
            target_point = Point3D(float(tp["x"]), float(tp.get("y", 0.0)), float(tp["z"]))

        results = self._combat.resolve_spell(
            actor,
            defenders,
            spell_action,
            target=target_point,
            slot_level=args.get("slot_level"),
        )
        per_target = []
        for entity, hit, damage, roll_detail, healing, healed in results:
            entry: Dict[str, Any] = {
                "target_id": entity.entity_id,
                "hit": hit,
                "damage": damage,
                "roll": _gate_roll(roll_detail, policy),
            }
            if healing:
                entry["healing"] = healing
                entry["healed_id"] = healed.entity_id if healed else None
            per_target.append(entry)

        return _ok(action=TOOL_CAST_SPELL, spell=spell_name, results=per_target)

    def _move(
        self, actor: Entity, args: Dict[str, Any], policy: InformationPolicy
    ) -> Dict[str, Any]:
        x = float(args["x"])
        z = float(args["z"])
        y = float(args.get("y", 0.0))
        self._combat.move_entity(actor, x, y, z)
        return _ok(
            action=TOOL_MOVE,
            position={"x": actor.x, "y": actor.y, "z": actor.z},
            movement_remaining=actor.resources.movement,
        )

    def _end_turn(
        self, actor: Entity, args: Dict[str, Any], policy: InformationPolicy
    ) -> Dict[str, Any]:
        self._combat.end_turn(actor.entity_id)
        return _ok(action=TOOL_END_TURN, ended_turn=True)
