// ── Input handlers ────────────────────────────────────────────────────────────
// All mouse, wheel, and toolbar button event listeners.

import {
    canvas, camera, CELL_PX, CELL_FEET,
    ZOOM_MIN, ZOOM_MAX, ZOOM_SPEED,
    tokens, state, createToken,
} from './state.js';
import { draw, getActionRangeFt } from './renderer.js';
import {
    updateInfoPanel, updateTargetPanel,
    setTargetingAction, openActionPanel, closeActionPanel,
    setActiveTool, updateCursor, refreshMoveReadout,
    moveReadout, measureReadout, infoPosEl, tgtPosEl,
} from './ui-panels.js';
import { wsSend, nextSeq } from './websocket.js';

export function initInputHandlers() {
    // ── Canvas mouse events ───────────────────────────────────────────────────

    canvas.addEventListener("mousedown", (e) => {
        if (e.button === 0 && state.activeTool === "move") {
            for (let i = tokens.length - 1; i >= 0; i--) {
                const t  = tokens[i];
                const dx = state.cursorWorld.x - t.x;
                const dy = state.cursorWorld.y - t.y;
                if (Math.sqrt(dx * dx + dy * dy) <= t.radius) {
                    state.draggingToken    = t;
                    state.dragOffset       = { x: dx, y: dy };
                    state.dragStartPos     = { x: t.x, y: t.y };
                    state.dragStartMovement = Math.round((t.resources?.movement ?? 0) * 10) / 10;
                    updateCursor();
                    return;
                }
            }
            return;
        }

        if (e.button === 0 && state.activeTool === "info") {
            const found = [...tokens].reverse().find(t => {
                const dx = state.cursorWorld.x - t.x;
                const dy = state.cursorWorld.y - t.y;
                return Math.sqrt(dx * dx + dy * dy) <= t.radius;
            }) ?? null;

            state.infoHoveredToken = found;
            updateInfoPanel(found);
            draw();
            return;
        }

        if (e.button === 0 && state.activeTool === "measure") {
            state.measuring    = true;
            state.measureStart = { x: state.cursorWorld.x, y: state.cursorWorld.y };
            state.measureEnd   = { x: state.cursorWorld.x, y: state.cursorWorld.y };
            return;
        }

        if (e.button === 0 && state.activeTool === "action") {
            if (state.targetingAction && state.actionToken) {
                const action = state.targetingAction;
                const reachFt       = getActionRangeFt(action);
                const maxRangeCells = (reachFt + state.actionToken.radius * CELL_FEET) / CELL_FEET;
                const dx   = state.cursorWorld.x - state.actionToken.x;
                const dy   = state.cursorWorld.y - state.actionToken.y;
                const dist = Math.sqrt(dx * dx + dy * dy);

                if (action.targeting_type === "aoe" && action.spell_range) {
                    if (dist <= maxRangeCells) {
                        wsSend({
                            type: "cast_spell",
                            seq: nextSeq(),
                            caster_id: state.actionToken.backendId ?? state.actionToken.id,
                            spell_name: action.name,
                            target_point: { x: state.cursorWorld.x, y: state.cursorWorld.y },
                        });
                        setTargetingAction(null);
                    }
                    return;
                }

                const canTargetSelf = action.can_target_self === true;
                const target = [...tokens].reverse().find(t => {
                    if (t === state.actionToken && !canTargetSelf) return false;
                    const tdx = state.cursorWorld.x - t.x;
                    const tdy = state.cursorWorld.y - t.y;
                    return Math.sqrt(tdx * tdx + tdy * tdy) <= t.radius;
                }) ?? null;

                if (target) {
                    if (action.spell_range) {
                        wsSend({
                            type: "cast_spell",
                            seq: nextSeq(),
                            caster_id: state.actionToken.backendId ?? state.actionToken.id,
                            spell_name: action.name,
                            target_ids: [target.backendId ?? target.id],
                        });
                    } else {
                        wsSend({
                            type: "attack",
                            seq: nextSeq(),
                            attacker_id: state.actionToken.backendId ?? state.actionToken.id,
                            defender_id: target.backendId ?? target.id,
                            action_name: action.name,
                        });
                    }
                    setTargetingAction(null);
                    return;
                }
            }

            const clicked = [...tokens].reverse().find(t => {
                const dx = state.cursorWorld.x - t.x;
                const dy = state.cursorWorld.y - t.y;
                return Math.sqrt(dx * dx + dy * dy) <= t.radius;
            }) ?? null;
            if (clicked) openActionPanel(clicked);
            else closeActionPanel();
            return;
        }

        if (e.button !== 1) return;
        e.preventDefault();
        state.panning = true;
        state.panLast = { x: e.clientX, y: e.clientY };
        updateCursor();
    });

    window.addEventListener("mousemove", (e) => {
        state.cursorWorld.x = (e.clientX - camera.x) / (CELL_PX * camera.zoom);
        state.cursorWorld.y = (e.clientY - camera.y) / (CELL_PX * camera.zoom);

        if (state.draggingToken) {
            state.draggingToken.x = state.cursorWorld.x - state.dragOffset.x;
            state.draggingToken.y = state.cursorWorld.y - state.dragOffset.y;

            const ddx    = (state.draggingToken.x - state.dragStartPos.x) * CELL_FEET;
            const ddy    = (state.draggingToken.y - state.dragStartPos.y) * CELL_FEET;
            const distFt = Math.round(Math.sqrt(ddx * ddx + ddy * ddy) * 10) / 10;
            moveReadout.textContent = `${distFt.toFixed(1)} / ${state.dragStartMovement.toFixed(1)} ft`;
            moveReadout.classList.toggle("over-limit", distFt > state.dragStartMovement);
            moveReadout.classList.add("visible");
        }

        if (state.measuring) {
            state.measureEnd = { x: state.cursorWorld.x, y: state.cursorWorld.y };
            const dx = (state.measureEnd.x - state.measureStart.x) * CELL_FEET;
            const dy = (state.measureEnd.y - state.measureStart.y) * CELL_FEET;
            measureReadout.textContent = `${Math.sqrt(dx * dx + dy * dy).toFixed(2)} ft`;
        }

        if (state.panning) {
            camera.x += e.clientX - state.panLast.x;
            camera.y += e.clientY - state.panLast.y;
            state.panLast = { x: e.clientX, y: e.clientY };
        }

        if (state.activeTool === "move" && !state.draggingToken) {
            const found = [...tokens].reverse().find(t => {
                const dx = state.cursorWorld.x - t.x;
                const dy = state.cursorWorld.y - t.y;
                return Math.sqrt(dx * dx + dy * dy) <= t.radius;
            }) ?? null;
            state.hoveringToken    = found !== null;
            state.moveHoveredToken = found;
            refreshMoveReadout();
            updateCursor();
        }

        if (state.activeTool === "info" && state.infoHoveredToken) {
            infoPosEl.textContent = `${(state.infoHoveredToken.x * CELL_FEET).toFixed(1)} ft, ${(state.infoHoveredToken.y * CELL_FEET).toFixed(1)} ft`;
        }

        if (state.targetingAction) {
            const found = [...tokens].reverse().find(t => {
                if (t === state.actionToken) return false;
                const dx = state.cursorWorld.x - t.x;
                const dy = state.cursorWorld.y - t.y;
                return Math.sqrt(dx * dx + dy * dy) <= t.radius;
            }) ?? null;

            if (found !== state.targetHovered) {
                state.targetHovered = found;
                updateTargetPanel(found);
            } else if (found) {
                tgtPosEl.textContent = `${(found.x * CELL_FEET).toFixed(1)} ft, ${(found.y * CELL_FEET).toFixed(1)} ft`;
            }
        }

        draw();
    });

    window.addEventListener("mouseup", (e) => {
        if (e.button === 0) {
            if (state.draggingToken) {
                const ddx    = (state.draggingToken.x - state.dragStartPos.x) * CELL_FEET;
                const ddy    = (state.draggingToken.y - state.dragStartPos.y) * CELL_FEET;
                const distFt = Math.round(Math.sqrt(ddx * ddx + ddy * ddy) * 10) / 10;

                if (distFt > state.dragStartMovement) {
                    state.draggingToken.x = state.dragStartPos.x;
                    state.draggingToken.y = state.dragStartPos.y;
                } else {
                    state.pendingMoveToken = state.draggingToken;
                    state.pendingMovePos   = { ...state.dragStartPos };
                    wsSend({
                        type: "move",
                        seq: nextSeq(),
                        entity_id: state.draggingToken.backendId ?? state.draggingToken.id,
                        position: { x: state.draggingToken.x, y: state.draggingToken.y },
                    });
                }

                state.dragStartPos  = null;
                state.draggingToken = null;
                refreshMoveReadout();
                updateCursor();
                draw();
                return;
            }
            if (state.measuring) {
                state.measuring    = false;
                state.measureStart = null;
                state.measureEnd   = null;
                measureReadout.textContent = "0.00 ft";
                draw();
                return;
            }
            return;
        }
        if (e.button !== 1) return;
        state.panning = false;
        updateCursor();
    });

    // Prevent middle-click scroll/autoscroll popup
    canvas.addEventListener("auxclick", (e) => { if (e.button === 1) e.preventDefault(); });

    // ── Zoom (scroll wheel) ───────────────────────────────────────────────────

    canvas.addEventListener("wheel", (e) => {
        e.preventDefault();

        const oldZoom = camera.zoom;
        const delta   = -e.deltaY * ZOOM_SPEED * camera.zoom;
        camera.zoom   = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, camera.zoom + delta));

        const mx     = e.offsetX;
        const my     = e.offsetY;
        const worldX = (mx - camera.x) / oldZoom;
        const worldY = (my - camera.y) / oldZoom;
        camera.x = mx - worldX * camera.zoom;
        camera.y = my - worldY * camera.zoom;

        draw();
    }, { passive: false });

    // ── Toolbar buttons ───────────────────────────────────────────────────────

    document.getElementById("tool-move").addEventListener("click",    () => setActiveTool("move"));
    document.getElementById("tool-measure").addEventListener("click", () => setActiveTool("measure"));
    document.getElementById("tool-info").addEventListener("click",    () => setActiveTool("info"));
    document.getElementById("tool-action").addEventListener("click",  () => setActiveTool("action"));

    document.getElementById("tool-add-token").addEventListener("click", () => {
        tokens.push(createToken());
        draw();
    });

    document.getElementById("btn-end-turn").addEventListener("click", () => {
        wsSend({ type: "end_turn", seq: nextSeq(), entity_id: state.currentEntityId });
    });
}
