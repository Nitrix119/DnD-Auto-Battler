# Turn-Order Enforcement + Active-Set Architecture

## Context

The combat system has no turn-order enforcement: any entity can attack, cast, or move at any time regardless of whose turn it is. The fix must also lay the architectural groundwork for a planned BG3-style feature where allied creatures with consecutive initiative slots act simultaneously, each ending their own turn independently.

## Architecture Decision

**Enforcement lives in `CombatSystem` (model layer), not in the WebSocket handlers.**
Game rules are transport-agnostic. The WS handlers already catch `ValueError` and forward it as an error message, so no new error-handling plumbing is needed. Any future adapter (CLI, AI loop, tests) automatically gets the same enforcement for free.

**`active_entity_ids` lives in `CombatSystem` as a computed property.**
`InitiativeTracker` owns the raw order and index; it should not know about team grouping. `CombatSystem` knows both, so it is the right place to compute the active set. The property starts as a singleton; future simultaneous turns only change this one property body — all call sites are untouched.

---

## Files to Modify

| File | Change |
|------|--------|
| `src/combat/combat_system.py` | Add `active_entity_ids` property + `_assert_active()` + guards in 3 action methods + optional `entity_id` param on `end_turn` |
| `web/routers/combat.py` | `handle_end_turn` extracts `entity_id`; `serialize_combat_state` exposes `active_entity_ids` |
| `web/static/js/battle.js` | One-line fix: include `entity_id: currentEntityId` in end-turn WS message |

`src/combat/initiative.py` and `src/combat/turn_manager.py` are **not modified**.

---

## Step-by-Step Implementation

### 1. `src/combat/combat_system.py`

#### 1a. Add `active_entity_ids` property

```python
@property
def active_entity_ids(self) -> frozenset[str]:
    """IDs of entities that may act this turn.
    Phase 1: always a singleton (one entity at current_turn_index).
    Phase 2 (future): expand to consecutive same-team group — only this
    property body changes; all enforcement call sites remain untouched.
    """
    current = self.initiative_tracker.get_current_entity()
    if current is None:
        return frozenset()
    return frozenset({current.entity_id})
```

#### 1b. Add `_assert_active(entity)` private method

```python
def _assert_active(self, entity: Entity) -> None:
    """Raise ValueError if entity is not in the active turn group."""
    if entity.entity_id not in self.active_entity_ids:
        current = self.initiative_tracker.get_current_entity()
        whose = current.name if current else "nobody"
        raise ValueError(
            f"It is not {entity.name}'s turn (active: {whose})"
        )
```

#### 1c. Insert guard as first line of each action method

- `resolve_attack(attacker, ...)` → `self._assert_active(attacker)`
- `resolve_spell(caster, ...)` → `self._assert_active(caster)`
- `move_entity(entity, ...)` → `self._assert_active(entity)`
- **`push_entity` is NOT guarded** — it is involuntary forced movement.

#### 1d. Add optional `entity_id` param to `end_turn`

```python
def end_turn(self, entity_id: Optional[str] = None) -> None:
    if entity_id is not None:
        entity = next((e for e in self.combatants if e.entity_id == entity_id), None)
        if entity is None:
            raise ValueError(f"Unknown entity_id: {entity_id!r}")
        self._assert_active(entity)
    # existing body unchanged ...
```

`None` default preserves backward compatibility with all existing unit tests and the AI loop.

---

### 2. `web/routers/combat.py`

#### 2a. `handle_end_turn` — extract and forward `entity_id`

```python
async def handle_end_turn(...) -> None:
    entity_id = msg.get("entity_id")          # NEW — None if not sent
    log_before = len(combat.log)
    combat.end_turn(entity_id=entity_id)      # passes through to model-layer guard
    # rest unchanged ...
```

#### 2b. `serialize_combat_state` — expose `active_entity_ids`

Add to the returned dict:
```python
"active_entity_ids": list(combat.active_entity_ids),
```

This is a trivial addition now, but it is the key frontend hook for future simultaneous-turn highlighting in the turn order bar.

---

### 3. `web/static/js/battle.js`

Change the End Turn button handler (one line):

```js
// Before:
wsSend({ type: "end_turn", seq: nextSeq() });

// After:
wsSend({ type: "end_turn", seq: nextSeq(), entity_id: currentEntityId });
```

---

## Future: Simultaneous Turns (Zero Rework Needed)

When the BG3-style feature is implemented, only these isolated changes are needed:

1. **`CombatSystem.active_entity_ids`** — expand to collect all consecutive same-team entities from `current_turn_index` forward (stop at team boundary or wrap). Entities with `team = None` always form singleton groups.

2. **`CombatSystem.end_turn` / `TurnManager`** — track a `_pending_done: set[str]` of active entities that have ended. Only call `_turn_manager.end_turn()` when the set is empty. `TurnManager` may grow an `end_turn_for(entity)` method.

3. **`serialize_combat_state`** — already exposes `active_entity_ids`; no change.

4. **`renderTurnOrderBar` (JS)** — change gold-border condition from `i === 0` to `activeEntityIds.has(id)`, where `activeEntityIds` is populated from `state.active_entity_ids`. The existing `currentEntityId` variable can remain for other non-bar uses.

The four `_assert_active()` call sites in `resolve_attack`, `resolve_spell`, `move_entity`, and `end_turn` are **never touched again**.

---

## Edge Cases

- **Dead entities' turns**: With no dead-skip logic in `InitiativeTracker.next_turn()`, a dead entity can become "active." No WS sender will act for them, so they harmlessly hold the turn until the AI/auto-advance logic calls `end_turn`. This is pre-existing behaviour, not introduced by this change.
- **`team = None` in future group expansion**: Must be treated as a singleton even though `None == None` is `True` in Python — explicitly guard with `if team is None: return frozenset({anchor.entity_id})`.
- **Existing tests calling `combat.end_turn()` with no args**: Continue to pass — the `None` default skips the entity check.

---

## Verification

1. Start a combat session and attempt to send an `attack` or `move` WebSocket message with the **non-active entity's ID** — expect a `{"type": "error", "command": "attack"|"move", "message": "It is not X's turn ..."}` response and no state change.
2. Send `end_turn` without `entity_id` — still works (backward compat).
3. Send `end_turn` with the correct `entity_id` — turn advances normally.
4. Send `end_turn` with a wrong `entity_id` — expect error, turn does not advance.
5. Run the existing test suite — all tests calling `combat.end_turn()` with no args must pass unchanged.
