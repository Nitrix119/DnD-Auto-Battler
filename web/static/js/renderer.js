// ── Renderer ──────────────────────────────────────────────────────────────────
// All canvas drawing: grid, tokens, overlays, floating labels.

import {
    canvas, ctx, camera,
    CELL_PX, CELL_FEET, COLOR_GRID, COLOR_LABEL,
    tokens, state,
} from './state.js';

// ── Coordinate conversion ─────────────────────────────────────────────────────

export function worldToScreen(cx, cy) {
    return {
        x: cx * CELL_PX * camera.zoom + camera.x,
        y: cy * CELL_PX * camera.zoom + camera.y,
    };
}

// ── Token drawing ─────────────────────────────────────────────────────────────

function drawOneToken(token) {
    const { x: sx, y: sy } = worldToScreen(token.x, token.y);
    const sr = token.radius * CELL_PX * camera.zoom;
    const dragging  = token === state.draggingToken;
    const infoHover = token === state.infoHoveredToken;
    const red = token.team === 2;

    if (infoHover) {
        ctx.beginPath();
        ctx.arc(sx, sy, sr + 5, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(255, 240, 150, 0.50)";
        ctx.lineWidth   = 1.5;
        ctx.stroke();
    }

    ctx.beginPath();
    ctx.arc(sx, sy, sr, 0, Math.PI * 2);
    if (red) {
        ctx.fillStyle = dragging ? "rgba(220, 90, 90, 0.70)" : "rgba(180, 60, 60, 0.50)";
    } else {
        ctx.fillStyle = dragging ? "rgba(100, 180, 255, 0.70)" : "rgba(80, 140, 255, 0.50)";
    }
    ctx.fill();
    ctx.strokeStyle = dragging ? "rgba(255, 255, 255, 1.00)" : "rgba(255, 255, 255, 0.80)";
    ctx.lineWidth   = dragging ? 2.0 : 1.5;
    ctx.stroke();

    if (sr >= 14) {
        const label = token.name.slice(0, Math.max(1, Math.floor(sr / 7)));
        ctx.font = `${Math.min(12, sr * 0.45)}px sans-serif`;
        ctx.textAlign    = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle    = "rgba(255, 255, 255, 0.85)";
        ctx.fillText(label, sx, sy);
        ctx.textAlign    = "left";
        ctx.textBaseline = "top";
    }
}

// Returns the effective range in feet for any action (attack or spell).
// touch → 5 ft, self → 0 (should not enter targeting), missing → 5 ft default.
export function getActionRangeFt(action) {
    if (action.spell_range) {
        const sr = action.spell_range;
        if (sr.type === "feet")  return sr.distance_ft;
        if (sr.type === "touch") return 5;
        return 0;  // "self" — guard; self spells bypass targeting entirely
    }
    return action.range_ft ?? 5;
}

function drawTargetingLine() {
    if (!state.targetingAction || !state.actionToken) return;

    const reachFt = getActionRangeFt(state.targetingAction);
    const maxRangeCells = (reachFt + state.actionToken.radius * CELL_FEET) / CELL_FEET;

    const dx   = state.cursorWorld.x - state.actionToken.x;
    const dy   = state.cursorWorld.y - state.actionToken.y;
    const dist = Math.sqrt(dx * dx + dy * dy);

    const clamped = Math.min(dist, maxRangeCells);
    const { x: sx, y: sy } = worldToScreen(state.actionToken.x, state.actionToken.y);
    let ex = sx, ey = sy;
    if (dist > 0) {
        const end = worldToScreen(
            state.actionToken.x + (dx / dist) * clamped,
            state.actionToken.y + (dy / dist) * clamped,
        );
        ex = end.x;
        ey = end.y;
    }

    const inRange   = dist <= maxRangeCells;
    const lineColor = inRange ? "rgba(255, 220, 80, 0.85)" : "rgba(255, 100, 80, 0.65)";

    const aoeShape = (state.targetingAction.aoe?.shape ?? "").toLowerCase();
    const isDirected = state.targetingAction.targeting_type === "aoe" &&
        (aoeShape === "cone" || aoeShape === "line");

    let osx = sx, osy = sy;
    if (isDirected && dist > 0) {
        const angle = Math.atan2(ey - sy, ex - sx);
        const tokenRadiusPx = state.actionToken.radius * CELL_PX * camera.zoom;
        osx = sx + Math.cos(angle) * tokenRadiusPx;
        osy = sy + Math.sin(angle) * tokenRadiusPx;
    }

    ctx.strokeStyle = lineColor;
    ctx.lineWidth   = 1.5;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.moveTo(osx, osy);
    ctx.lineTo(ex, ey);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = lineColor;
    ctx.beginPath();
    ctx.arc(ex, ey, 3, 0, Math.PI * 2);
    ctx.fill();

    if (state.targetingAction.targeting_type === "aoe" && state.targetingAction.aoe) {
        const aoe       = state.targetingAction.aoe;
        const aoeSizePx = (aoe.size_ft / CELL_FEET) * CELL_PX * camera.zoom;
        const aoeColor  = inRange ? "rgba(255, 100, 30, 0.30)" : "rgba(150, 150, 150, 0.20)";
        const aoeBorder = inRange ? "rgba(255, 160, 60, 0.85)" : "rgba(180, 180, 180, 0.50)";

        ctx.save();
        ctx.fillStyle   = aoeColor;
        ctx.strokeStyle = aoeBorder;
        ctx.lineWidth   = 1.5;
        ctx.setLineDash([]);

        if (aoeShape === "sphere" || aoeShape === "cylinder") {
            ctx.beginPath();
            ctx.arc(ex, ey, aoeSizePx, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
        } else if (aoeShape === "cube") {
            ctx.beginPath();
            ctx.rect(ex - aoeSizePx / 2, ey - aoeSizePx / 2, aoeSizePx, aoeSizePx);
            ctx.fill();
            ctx.stroke();
        } else if (aoeShape === "cone") {
            if (dist > 0) {
                const angle = Math.atan2(ey - sy, ex - sx);
                const fwdX  = Math.cos(angle) * aoeSizePx;
                const fwdY  = Math.sin(angle) * aoeSizePx;
                const perpX = Math.cos(angle + Math.PI / 2) * (aoeSizePx / 2);
                const perpY = Math.sin(angle + Math.PI / 2) * (aoeSizePx / 2);
                ctx.beginPath();
                ctx.moveTo(osx, osy);
                ctx.lineTo(osx + fwdX + perpX, osy + fwdY + perpY);
                ctx.lineTo(osx + fwdX - perpX, osy + fwdY - perpY);
                ctx.closePath();
                ctx.fill();
                ctx.stroke();
            }
        } else if (aoeShape === "line") {
            if (dist > 0) {
                const angle = Math.atan2(ey - sy, ex - sx);
                const lineWidthFt = aoe.width_ft ?? 5;
                const halfW = (lineWidthFt / CELL_FEET) * CELL_PX * camera.zoom / 2;
                const perpX = Math.cos(angle + Math.PI / 2) * halfW;
                const perpY = Math.sin(angle + Math.PI / 2) * halfW;
                const fwdX  = Math.cos(angle) * aoeSizePx;
                const fwdY  = Math.sin(angle) * aoeSizePx;
                ctx.beginPath();
                ctx.moveTo(osx - perpX, osy - perpY);
                ctx.lineTo(osx + perpX, osy + perpY);
                ctx.lineTo(osx + fwdX + perpX, osy + fwdY + perpY);
                ctx.lineTo(osx + fwdX - perpX, osy + fwdY - perpY);
                ctx.closePath();
                ctx.fill();
                ctx.stroke();
            }
        }

        ctx.restore();
    }
}

function drawMovementTrail() {
    if (!state.draggingToken || !state.dragStartPos) return;

    const { x: sx, y: sy } = worldToScreen(state.dragStartPos.x, state.dragStartPos.y);
    const { x: ex, y: ey } = worldToScreen(state.draggingToken.x, state.draggingToken.y);

    const color = "rgba(100, 200, 180, 0.75)";
    ctx.strokeStyle = color;
    ctx.lineWidth   = 1.5;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(ex, ey);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(sx, sy, 3, 0, Math.PI * 2);
    ctx.fill();
}

function drawTokens() {
    const acting  = state.targetingAction ? state.actionToken : null;
    const dragged = state.draggingToken;

    for (const token of tokens) {
        if (token !== acting && token !== dragged) drawOneToken(token);
    }

    drawTargetingLine();
    drawMovementTrail();

    if (acting && acting !== dragged) drawOneToken(acting);
    if (dragged) drawOneToken(dragged);
}

// ── Floating attack-roll labels ───────────────────────────────────────────────

const FLOAT_DURATION   = 2200;   // ms total lifetime
const FLOAT_RISE_CELLS = 1.1;    // cells to drift upward over lifetime

function _floatEaseOut(t) { return t * (2 - t); }

function renderFloatingLabels() {
    if (state.floatingLabels.length === 0) return;
    const now = performance.now();
    ctx.save();
    ctx.textAlign    = "center";
    ctx.textBaseline = "middle";
    for (let i = state.floatingLabels.length - 1; i >= 0; i--) {
        const lbl = state.floatingLabels[i];
        const t   = (now - lbl.t0) / FLOAT_DURATION;
        if (t >= 1) { state.floatingLabels.splice(i, 1); continue; }

        const rise  = FLOAT_RISE_CELLS * _floatEaseOut(t);
        const alpha = t > 0.55 ? 1 - (t - 0.55) / 0.45 : 1.0;

        const { x: sx, y: sy } = worldToScreen(lbl.wx, lbl.wy - rise);

        const fontSize = Math.round(Math.min(Math.max(11, 13 * camera.zoom), 20) * (lbl.scale ?? 1.0));
        ctx.font = `bold ${fontSize}px sans-serif`;

        const tw = ctx.measureText(lbl.text).width + 14;
        const th = fontSize + 8;

        ctx.fillStyle = `rgba(0, 0, 0, ${0.58 * alpha})`;
        ctx.beginPath();
        ctx.roundRect(sx - tw / 2, sy - th / 2, tw, th, th / 2);
        ctx.fill();

        ctx.fillStyle = lbl.hit
            ? `rgba(115, 210, 85,  ${alpha})`
            : `rgba(210, 85,  85,  ${alpha})`;
        ctx.fillText(lbl.text, sx, sy);
    }
    ctx.restore();
}

export function spawnFloatingLabel(wx, wy, text, hit, scale = 1.0) {
    state.floatingLabels.push({ text, wx, wy, hit, scale, t0: performance.now() });
    _ensureFloatLoop();
}

function _ensureFloatLoop() {
    if (state._floatLoopRunning) return;
    state._floatLoopRunning = true;
    requestAnimationFrame(_floatTick);
}

function _floatTick() {
    draw();
    if (state.floatingLabels.length > 0) {
        requestAnimationFrame(_floatTick);
    } else {
        state._floatLoopRunning = false;
    }
}

// ── Main draw ─────────────────────────────────────────────────────────────────

export function draw() {
    const w = canvas.width;
    const h = canvas.height;
    const cellSize = CELL_PX * camera.zoom;

    ctx.clearRect(0, 0, w, h);

    const colStart = Math.floor(-camera.x / cellSize) - 1;
    const colEnd   = Math.ceil((w - camera.x) / cellSize) + 1;
    const rowStart = Math.floor(-camera.y / cellSize) - 1;
    const rowEnd   = Math.ceil((h - camera.y) / cellSize) + 1;

    const MIN_LABEL_PX = 72;
    const labelStep = Math.ceil(MIN_LABEL_PX / cellSize);

    // ── Grid lines ────────────────────────────────────────────────────────
    ctx.strokeStyle = COLOR_GRID;
    ctx.lineWidth   = 0.5;

    for (let col = colStart; col <= colEnd; col++) {
        const x = camera.x + col * cellSize;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
    }

    for (let row = rowStart; row <= rowEnd; row++) {
        const y = camera.y + row * cellSize;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
    }

    // ── Coordinate labels ─────────────────────────────────────────────────
    const fontSize = Math.max(8, Math.min(11, cellSize * 0.22));
    ctx.font = `${fontSize}px monospace`;
    ctx.textBaseline = "top";
    ctx.fillStyle = COLOR_LABEL;

    const pad = 3;

    for (let col = colStart; col <= colEnd; col++) {
        if (col % labelStep !== 0) continue;
        for (let row = rowStart; row <= rowEnd; row++) {
            if (row % labelStep !== 0) continue;
            const sx = camera.x + col * cellSize + pad;
            const sy = camera.y + row * cellSize + pad;
            ctx.fillText(`${col * CELL_FEET},${row * CELL_FEET}`, sx, sy);
        }
    }

    // ── Tokens ────────────────────────────────────────────────────────────
    drawTokens();

    // ── Measure line ──────────────────────────────────────────────────────
    if (state.measuring && state.measureStart && state.measureEnd) {
        const { x: sx1, y: sy1 } = worldToScreen(state.measureStart.x, state.measureStart.y);
        const { x: sx2, y: sy2 } = worldToScreen(state.measureEnd.x,   state.measureEnd.y);

        ctx.strokeStyle = "rgba(255, 220, 80, 0.85)";
        ctx.lineWidth = 1.5;
        ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.moveTo(sx1, sy1);
        ctx.lineTo(sx2, sy2);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = "rgba(255, 220, 80, 0.85)";
        ctx.beginPath(); ctx.arc(sx1, sy1, 3, 0, Math.PI * 2); ctx.fill();
        ctx.beginPath(); ctx.arc(sx2, sy2, 3, 0, Math.PI * 2); ctx.fill();
    }

    // ── Floating attack-roll labels ───────────────────────────────────────
    renderFloatingLabels();

    // ── Cursor position readout ───────────────────────────────────────────
    const readout = `x: ${(state.cursorWorld.x * CELL_FEET).toFixed(2)} ft  y: ${(state.cursorWorld.y * CELL_FEET).toFixed(2)} ft`;
    ctx.font = "11px monospace";
    ctx.textBaseline = "bottom";
    const metrics = ctx.measureText(readout);
    const rw = metrics.width + 12;
    const rh = 20;
    const rx = 12;
    const ry = h - 12;
    ctx.fillStyle = "rgba(0, 0, 0, 0.45)";
    ctx.fillRect(rx - 6, ry - rh, rw, rh);
    ctx.fillStyle = "rgba(255, 255, 255, 0.70)";
    ctx.fillText(readout, rx, ry - 4);
}

// ── Resize ────────────────────────────────────────────────────────────────────

export function resize() {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
    draw();
}
