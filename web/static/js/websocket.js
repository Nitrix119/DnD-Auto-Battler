// ── WebSocket — combat session ────────────────────────────────────────────────
// Connection management, message dispatch, and all WS message handlers.

import { tokens, state } from './state.js';
import { draw, spawnFloatingLabel } from './renderer.js';
import {
    updateInfoPanel, updateTargetPanel,
    updateTurnOrderBar, updateResourcePanel, refreshMoveReadout,
} from './ui-panels.js';
import { animationManager } from './animation.js';

const wsStatusEl = document.getElementById("ws-status");

let ws               = null;
let seqCounter       = 0;
let _wsBackoffMs     = 250;
let _wsReconnectTimer = null;

export function nextSeq() { return ++seqCounter; }

export function wsSend(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

/** Calls cb immediately if the socket is already open, otherwise waits for open. */
export function whenOpen(cb) {
    if (ws && ws.readyState === WebSocket.OPEN) cb();
    else if (ws) ws.addEventListener("open", cb, { once: true });
}

export function connectWS() {
    if (_wsReconnectTimer !== null) {
        clearTimeout(_wsReconnectTimer);
        _wsReconnectTimer = null;
    }

    ws = new WebSocket(`ws://${location.host}/ws/combat`);

    ws.onopen = () => {
        wsStatusEl.className = "ws-connected";
        wsStatusEl.title = "Connected";
        _wsBackoffMs = 250;

        const sessionToken = sessionStorage.getItem("session_token");
        if (sessionToken) {
            wsSend({ type: "rejoin_combat", seq: nextSeq(), session_token: sessionToken });
        }
    };

    ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        console.log("[combat ws]", msg);

        switch (msg.type) {
            case "connected":          break;
            case "combat_started":     handleCombatStarted(msg);    break;
            case "rejoin_combat_ok":   handleRejoinCombatOk(msg);   break;
            case "action_result":      handleActionResult(msg);     break;
            case "move_result":        handleMoveResult(msg);       break;
            case "turn_changed":       handleTurnChanged(msg);      break;
            case "combat_ended":       handleCombatEnded(msg);      break;
            case "error":              handleWsError(msg);          break;
            default:
                console.warn("[combat ws] unknown message type:", msg.type);
        }
    };

    ws.onclose = () => {
        wsStatusEl.className = "ws-disconnected";
        wsStatusEl.title = `Disconnected — reconnecting in ${_wsBackoffMs}ms…`;
        _scheduleReconnect();
    };

    ws.onerror = () => {
        wsStatusEl.className = "ws-disconnected";
        wsStatusEl.title = "Connection error";
    };
}

function _scheduleReconnect() {
    if (_wsReconnectTimer !== null) return;
    _wsReconnectTimer = setTimeout(() => {
        _wsReconnectTimer = null;
        connectWS();
    }, _wsBackoffMs);
    _wsBackoffMs = Math.min(_wsBackoffMs * 2, 30_000);
}

// ── Message handlers ──────────────────────────────────────────────────────────

function updateFromCombatState(combatState) {
    state.currentEntityId = combatState.current_entity_id;
    state.activeEntityIds = new Set(combatState.active_entity_ids ?? (state.currentEntityId ? [state.currentEntityId] : []));
    for (const es of combatState.entities) {
        const token = tokens.find(t => (t.backendId ?? t.id) === es.entity_id);
        if (!token) continue;
        token.hp             = es.hp;
        token.maxHp          = es.max_hp;
        token.ac             = es.ac;
        token.x              = es.position.x;
        token.y              = es.position.y;
        token.resources      = es.resources;
        token.alive          = es.alive;
        token.statBreakdowns = es.stat_breakdowns ?? {};
        token.grantedActions = es.granted_actions ?? [];
    }
    if (state.infoHoveredToken) updateInfoPanel(state.infoHoveredToken);
    if (state.targetHovered)    updateTargetPanel(state.targetHovered);
    draw();
    refreshMoveReadout();
    if (combatState.turn_order) updateTurnOrderBar(combatState.turn_order, combatState.entities);
    updateResourcePanel();
}

function handleCombatStarted(msg) {
    if (msg.session_token) {
        sessionStorage.setItem("session_token", msg.session_token);
    }
    const idMap = msg.id_map;
    for (const token of tokens) {
        if (idMap[token.id]) {
            token.backendId = idMap[token.id];
        }
    }
    updateFromCombatState(msg.combat_state);
    console.log("[combat] started — initiative:", msg.initiative_order);
}

function handleRejoinCombatOk(msg) {
    const idMap = msg.id_map ?? {};
    for (const token of tokens) {
        if (idMap[token.id]) {
            token.backendId = idMap[token.id];
        }
    }
    updateFromCombatState(msg.combat_state);
    console.log("[combat] rejoined session — initiative:", msg.initiative_order);
}

async function handleActionResult(msg) {
    if (msg.action_type === "spell" && msg.animation && msg.animation.length > 0) {
        const casterToken = tokens.find(t => (t.backendId ?? t.id) === msg.attacker_id);
        const targetTokens = msg.results
            .map(r => tokens.find(t => (t.backendId ?? t.id) === r.target_id))
            .filter(Boolean);
        const context = {
            caster: casterToken ? { x: casterToken.x, y: casterToken.y } : { x: 0, y: 0 },
            casterRadius: casterToken ? casterToken.radius : 0,
            targets: targetTokens.map(t => ({ x: t.x, y: t.y })),
            targetPoint: msg.target_point || null,
        };
        await animationManager.play(msg.animation, context);
    }

    updateFromCombatState(msg.combat_state);

    for (const r of (msg.results ?? [])) {
        const target = tokens.find(t => (t.backendId ?? t.id) === r.target_id);
        if (!target) continue;
        const baseY = target.y - target.radius - 0.15;

        if (r.roll) {
            let text, success;
            if (r.roll.dc != null) {
                text = `SAVE ${r.roll.total} vs ${r.roll.dc} DC`;
                success = r.roll.save_success;
            } else {
                text = `ATK ${r.roll.total} vs ${r.roll.ac} AC`;
                success = r.hit;
            }
            spawnFloatingLabel(target.x, baseY,        text,                    success);
            spawnFloatingLabel(target.x, baseY - 0.55, "-" + String(r.damage),  success, 1.45);
        }

        if (r.healing > 0) {
            const healedToken = tokens.find(t => (t.backendId ?? t.id) === (r.healed_id ?? r.target_id));
            if (healedToken) {
                const healY = healedToken.y - healedToken.radius - 0.15;
                spawnFloatingLabel(healedToken.x, healY, "+" + String(r.healing), true, 1.45);
            }
        }
    }

    for (const line of (msg.log || [])) {
        console.log("[combat log]", line);
    }
}

function handleMoveResult(msg) {
    state.pendingMoveToken = null;
    state.pendingMovePos   = null;
    updateFromCombatState(msg.combat_state);
}

function handleTurnChanged(msg) {
    updateFromCombatState(msg.combat_state);
    console.log(`[combat] turn changed — R${msg.round}T${msg.turn}, entity: ${msg.current_entity_id}`);
}

function handleCombatEnded(msg) {
    updateFromCombatState(msg.combat_state);
    console.log("[combat] ended — winner:", msg.winner);
}

function handleWsError(msg) {
    console.error(`[combat error] ${msg.command}: ${msg.message}`);
    if (msg.command === "move" && state.pendingMoveToken && state.pendingMovePos) {
        state.pendingMoveToken.x = state.pendingMovePos.x;
        state.pendingMoveToken.y = state.pendingMovePos.y;
        draw();
    }
    state.pendingMoveToken = null;
    state.pendingMovePos   = null;
}
