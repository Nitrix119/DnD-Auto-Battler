// ── Playback data ───────────────────────────────────────────────────────────
// Pure transforms: a match transcript (JSONL) → an ordered list of playback
// *steps*, each a fully reconstructed snapshot of the board plus a caption and an
// optional visual effect. No DOM, no canvas — kept side-effect-free so it can be
// reasoned about (and unit-tested) in isolation.
//
// Coordinate convention (mirrors web/routers/combat.py `backend_to_frontend`):
//   frontend cell x = feet.x / CELL_FEET,  frontend cell y = feet.z / CELL_FEET
// (feet.y is "up" and ignored on the 2D board). CELL_FEET = 5 — keep in sync with
// the copies in state.js and web/routers/combat.py.

const CELL_FEET = 5;

export function parseJsonl(text) {
    return text
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line.length > 0)
        .map((line) => JSON.parse(line));
}

// A snapshot entity (backend feet) → the flat, cell-space shape a step carries.
function entityFromSnapshot(e) {
    return {
        id: e.entity_id,
        name: e.name,
        team: e.team,
        cellX: e.position.x / CELL_FEET,
        cellY: e.position.z / CELL_FEET,
        sizeFt: e.size_ft ?? CELL_FEET,
        hp: e.hp ?? null,
        maxHp: e.max_hp ?? null,
        ac: e.ac ?? null,
        alive: e.alive !== false,
        conditions: e.conditions ?? [],
    };
}

function entitiesFromSnapshot(snapshot) {
    const out = {};
    for (const e of snapshot.entities) out[e.entity_id] = entityFromSnapshot(e);
    return out;
}

// Reconcile the running fold to an authoritative snapshot (self-heals any drift
// the incremental fold introduced — the reason turn_end snapshots exist).
function reconcile(entities, snapshot) {
    for (const e of snapshot.entities) entities[e.entity_id] = entityFromSnapshot(e);
}

const clone = (obj) => JSON.parse(JSON.stringify(obj));

function nameOf(entities, id) {
    return entities[id]?.name ?? (id ? id.slice(0, 8) : "?");
}

// Build a step's caption + fx for one `action` record.
function describeAction(entities, rec) {
    const actor = nameOf(entities, rec.actor_id);
    const call = rec.call || {};
    const args = call.arguments || {};
    const res = rec.result || {};

    if (res.ok === false) {
        return { caption: `${actor}: illegal ${call.name} (${res.error ?? "?"})`, fx: null };
    }

    if (call.name === "attack") {
        const target = nameOf(entities, res.target_id);
        const weapon = args.action_name ? ` with ${args.action_name}` : "";
        const roll = res.roll || {};
        const rollTxt =
            roll.attack_total != null
                ? ` (roll ${roll.attack_total} vs AC ${roll.target_ac})`
                : "";
        if (res.hit) {
            return {
                caption: `${actor} attacks ${target}${weapon}: HIT for ${res.damage}${rollTxt}`,
                fx: { targetId: res.target_id, text: `-${res.damage}`, hit: true },
            };
        }
        return {
            caption: `${actor} attacks ${target}${weapon}: MISS${rollTxt}`,
            fx: { targetId: res.target_id, text: "miss", hit: false },
        };
    }

    if (call.name === "move") {
        const p = res.position || {};
        const cx = (p.x ?? 0) / CELL_FEET;
        const cy = (p.z ?? 0) / CELL_FEET;
        return { caption: `${actor} moves to (${cx.toFixed(0)}, ${cy.toFixed(0)})`, fx: null };
    }

    // cast_spell / other named tools: show the tool + any target.
    const target = res.target_id ? ` → ${nameOf(entities, res.target_id)}` : "";
    return { caption: `${actor}: ${call.name}${target}`, fx: null };
}

/**
 * Fold a transcript's records into ordered playback steps.
 *
 * @param {Array<object>} records - parsed transcript records (see transcript.py).
 * @returns {{steps: Array, statBlocks: object, teams: object, meta: object}}
 *   `steps[i]` = { recordIndex, round, turn, currentId, entities, caption, fx }.
 *   `entities` is a per-step deep copy keyed by id (so scrubbing backward is exact).
 *   `statBlocks` maps entity id → the static stat block logged at match_start
 *   (empty when the transcript predates that logging).
 */
export function buildSteps(records) {
    const start = records.find((r) => r.kind === "match_start") || {};
    const statBlocks = {};
    for (const c of start.combatants || []) statBlocks[c.entity_id] = c;

    // Seed frame 0: prefer the pre-combat snapshot; else the first turn_end snapshot.
    let entities;
    if (start.initial_state) {
        entities = entitiesFromSnapshot(start.initial_state);
    } else {
        const firstTurnEnd = records.find((r) => r.kind === "turn_end");
        entities = firstTurnEnd ? entitiesFromSnapshot(firstTurnEnd.state) : {};
    }

    const teams = start.teams || {};
    const steps = [];
    let round = 0;
    let turn = 0;
    let currentId = null;

    const names = Object.values(entities).map((e) => e.name);
    steps.push({
        recordIndex: start.i ?? 0,
        round,
        turn,
        currentId,
        entities: clone(entities),
        caption: names.length ? `Match start — ${names.join(" vs ")}` : "Match start",
        fx: null,
    });

    for (const rec of records) {
        switch (rec.kind) {
            case "turn_start": {
                round = rec.round ?? round;
                turn = rec.turn ?? turn;
                currentId = rec.entity_id ?? currentId;
                steps.push({
                    recordIndex: rec.i,
                    round,
                    turn,
                    currentId,
                    entities: clone(entities),
                    caption: `${nameOf(entities, currentId)}'s turn`,
                    fx: null,
                });
                break;
            }
            case "action": {
                const call = rec.call || {};
                // end_turn carries no visible change — fold nothing, add no step.
                if (call.name === "end_turn") break;

                const { caption, fx } = describeAction(entities, rec);
                // Apply the visible effect to the running fold.
                const res = rec.result || {};
                if (call.name === "attack" && res.hit && res.target_id in entities) {
                    const t = entities[res.target_id];
                    if (t.hp != null) t.hp = Math.max(0, t.hp - (res.damage || 0));
                } else if (call.name === "move" && rec.actor_id in entities && res.position) {
                    const a = entities[rec.actor_id];
                    a.cellX = (res.position.x ?? 0) / CELL_FEET;
                    a.cellY = (res.position.z ?? 0) / CELL_FEET;
                }
                steps.push({
                    recordIndex: rec.i,
                    round,
                    turn,
                    currentId,
                    entities: clone(entities),
                    caption,
                    fx,
                });
                break;
            }
            case "turn_end": {
                // Authoritative reconciliation — corrects any fold drift for later turns.
                if (rec.state) reconcile(entities, rec.state);
                break;
            }
            case "match_end": {
                const winner = rec.winner == null ? "draw" : `Team ${rec.winner}`;
                steps.push({
                    recordIndex: rec.i,
                    round,
                    turn,
                    currentId,
                    entities: clone(entities),
                    caption: `Match over — ${winner} (${rec.reason}) after ${rec.rounds} rounds`,
                    fx: null,
                });
                break;
            }
            default:
                break;
        }
    }

    return { steps, statBlocks, teams, meta: { seed: start.seed, roundCap: start.round_cap } };
}

/** Global bounding box (in cells) over every step, for camera auto-fit. */
export function boundsOf(steps) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const step of steps) {
        for (const e of Object.values(step.entities)) {
            const r = e.sizeFt / CELL_FEET / 2;
            minX = Math.min(minX, e.cellX - r);
            maxX = Math.max(maxX, e.cellX + r);
            minY = Math.min(minY, e.cellY - r);
            maxY = Math.max(maxY, e.cellY + r);
        }
    }
    if (!isFinite(minX)) return { minX: -1, minY: -1, maxX: 1, maxY: 1 };
    return { minX, minY, maxX, maxY };
}
