// ── Session guard ─────────────────────────────────────────────────────────────
// The battle page is only valid when navigated to from the setup page.
// If the flag is absent (direct load, reload, back-button), redirect home.
if (!sessionStorage.getItem("combat_ready")) {
    location.replace("/");
    throw new Error("No active combat session — redirecting to setup.");
}
sessionStorage.removeItem("combat_ready");

const canvas = document.getElementById("grid");
const ctx = canvas.getContext("2d");

// Camera state: x/y are the screen-space offset of world origin (0,0)
const camera = { x: 0, y: 0, zoom: 1.0 };

const CELL_PX    = 50;    // base cell size in pixels at zoom 1 (1 cell = 5 ft)
const CELL_FEET  = 5;     // feet per grid cell
const ZOOM_MIN   = 0.10;
const ZOOM_MAX   = 8.0;
const ZOOM_SPEED = 0.001;

// Colours
const COLOR_GRID  = "rgba(255, 255, 255, 0.07)";
const COLOR_LABEL = "rgba(255, 255, 255, 0.25)";

// Custom cursor for the info tool — magnifying glass built from an inline SVG
const CURSOR_INFO = (() => {
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20">'
              + '<circle cx="8" cy="8" r="5" fill="none" stroke="white" stroke-width="1.5"/>'
              + '<line x1="12" y1="12" x2="17" y2="17" stroke="white" stroke-width="1.8" stroke-linecap="round"/>'
              + '</svg>';
    return `url('data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}') 8 8, zoom-in`;
})();

// ── Token registry ────────────────────────────────────────────────────────────
//
// Each token is a plain object representing a battlefield entity.
// `x` and `y` are the canonical world-space position in cell units.
// `team`: 1 = ally (blue), 2 = enemy (red), 0 = neutral.
// Creature tokens are pre-populated from JSON; manual tokens have null fields.

// D&D 5e size → token radius in cell units (1 cell = 5 ft).
// Radius = half the creature's space, so the circle fills its occupied squares.
const SIZE_RADIUS = {
    tiny:        0.25,   //  2.5 ft radius —  5 ft space (shares squares)
    small:       0.5,    //  2.5 ft radius —  5 ft space
    medium:      0.5,    //  2.5 ft radius —  5 ft space
    large:       1.0,    //  5 ft radius   — 10 ft space
    huge:        1.5,    //  7.5 ft radius — 15 ft space
    gargantuan:  2.0,    // 10 ft radius   — 20 ft space
};

const tokens = [];

function createToken(x = 0.5, y = 0.5, creatureData = null, team = 0, creaturePath = null) {
    const size   = creatureData?.size?.toLowerCase() ?? "medium";
    const radius = SIZE_RADIUS[size] ?? SIZE_RADIUS.medium;
    return {
        id:        crypto.randomUUID(),
        _creaturePath: creaturePath,  // relative path for backend start_combat
        x,
        y,
        radius,    // cell units — derived from creature size
        team,
        name:      creatureData?.name           ?? "Token",
        hp:        creatureData?.hit_points     ?? null,
        maxHp:     creatureData?.hit_points_max ?? null,
        ac:        creatureData?.armor_class    ?? null,
        abilities: creatureData?.abilities      ?? null,
        actions:   creatureData?.actions        ?? [],
        spells:    creatureData?.known_spells   ?? [],  // raw name list
        spellData: [],                                  // resolved spell objects (populated async)
    };
}

// Custom cursor for the action tool — lightning bolt
const CURSOR_ACTION = (() => {
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20">'
              + '<polygon points="11,1 4,11 10,11 9,19 16,9 10,9" fill="white" opacity="0.9"/>'
              + '</svg>';
    return `url('data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}') 10 10, crosshair`;
})();

// ── Tool state ────────────────────────────────────────────────────────────────

let activeTool       = null;   // 'move' | 'measure' | 'info' | 'action' | null
let measuring        = false;
let measureStart     = null;   // { x, y } in cell units
let measureEnd       = null;   // { x, y } in cell units
let draggingToken    = null;   // the token currently being dragged
let dragOffset       = { x: 0, y: 0 };  // cursor-to-centre offset at drag start
let hoveringToken    = false;  // whether the cursor is over a draggable token
let infoHoveredToken = null;   // token currently inspected by the info tool
let actionToken      = null;   // token whose action panel is open
let targetingAction  = null;   // action object currently being targeted
let targetHovered    = null;   // token under cursor during targeting
let currentEntityId  = null;   // entity whose turn it is (from backend)

// ── Resize ────────────────────────────────────────────────────────────────────

function resize() {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
    draw();
}

window.addEventListener("resize", resize);

// ── Rendering ─────────────────────────────────────────────────────────────────

function worldToScreen(cx, cy) {
    return {
        x: cx * CELL_PX * camera.zoom + camera.x,
        y: cy * CELL_PX * camera.zoom + camera.y,
    };
}

function drawOneToken(token) {
    const { x: sx, y: sy } = worldToScreen(token.x, token.y);
    const sr = token.radius * CELL_PX * camera.zoom;
    const dragging  = token === draggingToken;
    const infoHover = token === infoHoveredToken;
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
function getActionRangeFt(action) {
    if (action.spell_range) {
        const sr = action.spell_range;
        if (sr.type === "feet")  return sr.distance_ft;
        if (sr.type === "touch") return 5;
        return 0;  // "self" — guard; self spells bypass targeting entirely
    }
    return action.range_ft ?? 5;
}

function drawTargetingLine() {
    if (!targetingAction || !actionToken) return;

    // Max range from token centre = action range + attacker's own radius (centre → edge)
    const reachFt = getActionRangeFt(targetingAction);
    const maxRangeCells = (reachFt + actionToken.radius * CELL_FEET) / CELL_FEET;

    const dx   = cursorWorld.x - actionToken.x;
    const dy   = cursorWorld.y - actionToken.y;
    const dist = Math.sqrt(dx * dx + dy * dy);

    // Clamp end-point to max range; draw toward cursor if within range
    const clamped = Math.min(dist, maxRangeCells);
    const { x: sx, y: sy } = worldToScreen(actionToken.x, actionToken.y);
    let ex = sx, ey = sy;
    if (dist > 0) {
        const end = worldToScreen(
            actionToken.x + (dx / dist) * clamped,
            actionToken.y + (dy / dist) * clamped,
        );
        ex = end.x;
        ey = end.y;
    }

    const inRange   = dist <= maxRangeCells;
    const lineColor = inRange ? "rgba(255, 220, 80, 0.85)" : "rgba(255, 100, 80, 0.65)";

    ctx.strokeStyle = lineColor;
    ctx.lineWidth   = 1.5;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(ex, ey);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = lineColor;
    ctx.beginPath();
    ctx.arc(ex, ey, 3, 0, Math.PI * 2);
    ctx.fill();
}

function drawTokens() {
    const acting = targetingAction ? actionToken : null;

    // Phase 1 — all tokens except the acting one
    for (const token of tokens) {
        if (token !== acting) drawOneToken(token);
    }

    // Phase 2 — targeting line (above other tokens, below acting token)
    drawTargetingLine();

    // Phase 3 — acting token on top
    if (acting) drawOneToken(acting);
}

function draw() {
    const w = canvas.width;
    const h = canvas.height;
    const cellSize = CELL_PX * camera.zoom;

    ctx.clearRect(0, 0, w, h);

    // Compute which grid columns/rows are visible
    const colStart = Math.floor(-camera.x / cellSize) - 1;
    const colEnd   = Math.ceil((w - camera.x) / cellSize) + 1;
    const rowStart = Math.floor(-camera.y / cellSize) - 1;
    const rowEnd   = Math.ceil((h - camera.y) / cellSize) + 1;

    // Adaptive label density: show a label every N cells so text never overlaps
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
    if (measuring && measureStart && measureEnd) {
        const { x: sx1, y: sy1 } = worldToScreen(measureStart.x, measureStart.y);
        const { x: sx2, y: sy2 } = worldToScreen(measureEnd.x,   measureEnd.y);

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

    // ── Cursor position readout ───────────────────────────────────────────
    const readout = `x: ${(cursorWorld.x * CELL_FEET).toFixed(2)} ft  y: ${(cursorWorld.y * CELL_FEET).toFixed(2)} ft`;
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

// ── Cursor management ─────────────────────────────────────────────────────────

function updateCursor() {
    if (panning) {
        canvas.style.cursor = "grabbing";
    } else if (activeTool === "move") {
        if (draggingToken)  canvas.style.cursor = "grabbing";
        else if (hoveringToken) canvas.style.cursor = "grab";
        else                canvas.style.cursor = "default";
    } else if (activeTool === "measure") {
        canvas.style.cursor = "crosshair";
    } else if (activeTool === "info") {
        canvas.style.cursor = CURSOR_INFO;
    } else if (activeTool === "action") {
        canvas.style.cursor = CURSOR_ACTION;
    } else {
        canvas.style.cursor = "";  // falls back to CSS `grab`
    }
}

// ── Input state ───────────────────────────────────────────────────────────────

let panning     = false;
let panLast     = { x: 0, y: 0 };
let cursorWorld = { x: 0, y: 0 };

// ── Mouse events ──────────────────────────────────────────────────────────────

canvas.addEventListener("mousedown", (e) => {
    if (e.button === 0 && activeTool === "move") {
        // Pick the topmost token under the cursor (reverse order = front first)
        for (let i = tokens.length - 1; i >= 0; i--) {
            const t  = tokens[i];
            const dx = cursorWorld.x - t.x;
            const dy = cursorWorld.y - t.y;
            if (Math.sqrt(dx * dx + dy * dy) <= t.radius) {
                draggingToken = t;
                dragOffset    = { x: dx, y: dy };
                updateCursor();
                return;
            }
        }
        return;
    }

    if (e.button === 0 && activeTool === "measure") {
        measuring    = true;
        measureStart = { x: cursorWorld.x, y: cursorWorld.y };
        measureEnd   = { x: cursorWorld.x, y: cursorWorld.y };
        return;
    }

    if (e.button === 0 && activeTool === "action") {
        // If targeting is active, clicking on a valid target executes the action
        if (targetingAction && actionToken) {
            const target = [...tokens].reverse().find(t => {
                if (t === actionToken) return false;
                const dx = cursorWorld.x - t.x;
                const dy = cursorWorld.y - t.y;
                return Math.sqrt(dx * dx + dy * dy) <= t.radius;
            }) ?? null;

            if (target) {
                const action = targetingAction;
                if (action.spell_range) {
                    // Spell
                    const payload = {
                        type: "cast_spell",
                        seq: nextSeq(),
                        caster_id: actionToken.id,
                        spell_name: action.name,
                    };
                    if (action.targeting_type === "aoe") {
                        payload.target_point = { x: cursorWorld.x, y: cursorWorld.y };
                    } else {
                        payload.target_ids = [target.id];
                    }
                    wsSend(payload);
                } else {
                    // Attack
                    wsSend({
                        type: "attack",
                        seq: nextSeq(),
                        attacker_id: actionToken.id,
                        defender_id: target.id,
                        action_name: action.name,
                    });
                }
                setTargetingAction(null);
                return;
            }
        }

        const clicked = [...tokens].reverse().find(t => {
            const dx = cursorWorld.x - t.x;
            const dy = cursorWorld.y - t.y;
            return Math.sqrt(dx * dx + dy * dy) <= t.radius;
        }) ?? null;
        if (clicked) openActionPanel(clicked);
        else closeActionPanel();
        return;
    }

    if (e.button !== 1) return;
    e.preventDefault();
    panning = true;
    panLast = { x: e.clientX, y: e.clientY };
    updateCursor();
});

window.addEventListener("mousemove", (e) => {
    cursorWorld.x = (e.clientX - camera.x) / (CELL_PX * camera.zoom);
    cursorWorld.y = (e.clientY - camera.y) / (CELL_PX * camera.zoom);

    if (draggingToken) {
        // Update the token's canonical position directly
        draggingToken.x = cursorWorld.x - dragOffset.x;
        draggingToken.y = cursorWorld.y - dragOffset.y;
    }

    if (measuring) {
        measureEnd = { x: cursorWorld.x, y: cursorWorld.y };
        const dx = (measureEnd.x - measureStart.x) * CELL_FEET;
        const dy = (measureEnd.y - measureStart.y) * CELL_FEET;
        measureReadout.textContent = `${Math.sqrt(dx * dx + dy * dy).toFixed(2)} ft`;
    }

    if (panning) {
        camera.x += e.clientX - panLast.x;
        camera.y += e.clientY - panLast.y;
        panLast = { x: e.clientX, y: e.clientY };
    }

    // Update hover state for move tool cursor feedback
    if (activeTool === "move" && !draggingToken) {
        hoveringToken = tokens.some(t => {
            const dx = cursorWorld.x - t.x;
            const dy = cursorWorld.y - t.y;
            return Math.sqrt(dx * dx + dy * dy) <= t.radius;
        });
        updateCursor();
    }

    // Info tool — find topmost token under cursor and update the panel
    if (activeTool === "info") {
        const found = [...tokens].reverse().find(t => {
            const dx = cursorWorld.x - t.x;
            const dy = cursorWorld.y - t.y;
            return Math.sqrt(dx * dx + dy * dy) <= t.radius;
        }) ?? null;

        if (found !== infoHoveredToken) {
            infoHoveredToken = found;
            updateInfoPanel(found);
        } else if (found) {
            // Position changes even without token swap — refresh the pos line
            infoPosEl.textContent = `${(found.x * CELL_FEET).toFixed(1)} ft, ${(found.y * CELL_FEET).toFixed(1)} ft`;
        }
    }

    // Target panel — show enemy stats when hovering a token during targeting
    if (targetingAction) {
        const found = [...tokens].reverse().find(t => {
            if (t === actionToken) return false;
            const dx = cursorWorld.x - t.x;
            const dy = cursorWorld.y - t.y;
            return Math.sqrt(dx * dx + dy * dy) <= t.radius;
        }) ?? null;

        if (found !== targetHovered) {
            targetHovered = found;
            updateTargetPanel(found);
        } else if (found) {
            tgtPosEl.textContent = `${(found.x * CELL_FEET).toFixed(1)} ft, ${(found.y * CELL_FEET).toFixed(1)} ft`;
        }
    }

    draw();
});

window.addEventListener("mouseup", (e) => {
    if (e.button === 0) {
        if (draggingToken) {
            // Send final position to backend for validation
            wsSend({
                type: "move",
                seq: nextSeq(),
                entity_id: draggingToken.id,
                position: { x: draggingToken.x, y: draggingToken.y },
            });
            draggingToken = null;
            updateCursor();
            draw();
            return;
        }
        if (measuring) {
            measuring    = false;
            measureStart = null;
            measureEnd   = null;
            measureReadout.textContent = "0.00 ft";
            draw();
            return;
        }
        return;
    }
    if (e.button !== 1) return;
    panning = false;
    updateCursor();
});

// Prevent middle-click scroll/autoscroll popup in browsers
canvas.addEventListener("auxclick", (e) => { if (e.button === 1) e.preventDefault(); });

// ── Zoom (scroll wheel) ───────────────────────────────────────────────────────

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

// ── Toolbar ───────────────────────────────────────────────────────────────────

const btnMove        = document.getElementById("tool-move");
const btnMeasure     = document.getElementById("tool-measure");
const btnInfo        = document.getElementById("tool-info");
const btnAction      = document.getElementById("tool-action");
const btnAddToken    = document.getElementById("tool-add-token");
const measureReadout = document.getElementById("measure-readout");

// Action panel
const actionPanel       = document.getElementById("action-panel");
const actionActorNameEl = document.getElementById("action-actor-name");
const actionListEl      = document.getElementById("action-list");

// Target panel
const targetPanel  = document.getElementById("target-panel");
const tgtNameEl    = document.getElementById("tgt-name");
const tgtHpEl      = document.getElementById("tgt-hp");
const tgtAcEl      = document.getElementById("tgt-ac");
const tgtPosEl     = document.getElementById("tgt-pos");
const tgtStrEl     = document.getElementById("tgt-str");
const tgtDexEl     = document.getElementById("tgt-dex");
const tgtConEl     = document.getElementById("tgt-con");
const tgtIntEl     = document.getElementById("tgt-int");
const tgtWisEl     = document.getElementById("tgt-wis");
const tgtChaEl     = document.getElementById("tgt-cha");

function updateTargetPanel(token) {
    if (!token) {
        targetPanel.classList.remove("visible");
        return;
    }
    const abs = token.abilities;
    tgtNameEl.textContent = `Target: ${token.name}`;
    tgtHpEl.textContent   = token.hp !== null ? `${token.hp} / ${token.maxHp}` : "—";
    tgtAcEl.textContent   = token.ac !== null ? token.ac : "—";
    tgtPosEl.textContent  = `${(token.x * CELL_FEET).toFixed(1)} ft, ${(token.y * CELL_FEET).toFixed(1)} ft`;
    tgtStrEl.textContent  = abs ? abs.strength     : "—";
    tgtDexEl.textContent  = abs ? abs.dexterity    : "—";
    tgtConEl.textContent  = abs ? abs.constitution : "—";
    tgtIntEl.textContent  = abs ? abs.intelligence : "—";
    tgtWisEl.textContent  = abs ? abs.wisdom       : "—";
    tgtChaEl.textContent  = abs ? abs.charisma     : "—";
    targetPanel.classList.add("visible");
}

// Targeting banner
const targetingBanner    = document.getElementById("targeting-banner");
const targetingLabelEl   = document.getElementById("targeting-label");
const targetingCancelBtn = document.getElementById("targeting-cancel");

function setTargetingAction(action) {
    targetingAction = action;
    // Toggle active class on all action buttons
    for (const btn of actionListEl.querySelectorAll(".action-btn")) {
        btn.classList.toggle("active", btn.dataset.actionName === action?.name);
    }
    if (action) {
        targetingLabelEl.textContent = `Targeting: ${action.name}`;
        targetingBanner.classList.add("visible");
    } else {
        targetingBanner.classList.remove("visible");
        targetHovered = null;
        updateTargetPanel(null);
    }
}

function makeActionSection(label, buildBody) {
    const wrapper = document.createElement("div");
    wrapper.className = "action-section";

    const header = document.createElement("div");
    header.className = "action-section-header";
    header.innerHTML = `<span class="section-arrow">▾</span>${label}`;
    header.addEventListener("click", () => wrapper.classList.toggle("collapsed"));

    const body = document.createElement("div");
    body.className = "action-section-body";
    buildBody(body);

    wrapper.appendChild(header);
    wrapper.appendChild(body);
    return wrapper;
}

function makeEmptyNote(text) {
    const el = document.createElement("div");
    el.className = "action-empty";
    el.textContent = text;
    return el;
}

function openActionPanel(token) {
    actionToken = token;
    setTargetingAction(null);

    actionActorNameEl.textContent = token.name;
    actionListEl.innerHTML = "";

    // ── Attacks ──────────────────────────────────────────────────────────────
    actionListEl.appendChild(makeActionSection("Attacks", (body) => {
        if (token.actions.length === 0) {
            body.appendChild(makeEmptyNote("None."));
        } else {
            for (const action of token.actions) {
                const btn = document.createElement("button");
                btn.className = "action-btn";
                btn.textContent = action.name;
                btn.dataset.actionName = action.name;
                btn.addEventListener("click", () => {
                    setTargetingAction(targetingAction?.name === action.name ? null : action);
                });
                body.appendChild(btn);
            }
        }
    }));

    // ── Spells ───────────────────────────────────────────────────────────────
    actionListEl.appendChild(makeActionSection("Spells", (body) => {
        if (token.spells.length === 0) {
            body.appendChild(makeEmptyNote("None."));
        } else if (token.spellData.length === 0) {
            body.appendChild(makeEmptyNote("Loading…"));
        } else {
            for (const spell of token.spellData) {
                const btn = document.createElement("button");
                btn.className = "action-btn action-btn-spell";
                btn.textContent = spell.name;
                btn.dataset.actionName = spell.name;

                if (spell.spell_range?.type === "self") {
                    // Self-targeting: fires instantly — no targeting cursor needed
                    btn.title = "Self — instant cast (not yet functional)";
                    btn.addEventListener("click", () => setTargetingAction(null));
                } else {
                    btn.addEventListener("click", () => {
                        setTargetingAction(targetingAction?.name === spell.name ? null : spell);
                    });
                }

                body.appendChild(btn);
            }
        }
    }));

    // ── Other ─────────────────────────────────────────────────────────────────
    actionListEl.appendChild(makeActionSection("Other", (body) => {
        body.appendChild(makeEmptyNote("None."));
    }));

    actionPanel.classList.add("visible");
}

function closeActionPanel() {
    actionToken = null;
    setTargetingAction(null);
    actionPanel.classList.remove("visible");
}

targetingCancelBtn.addEventListener("click", () => setTargetingAction(null));
const infoPanel      = document.getElementById("info-panel");
const infoNameEl     = document.getElementById("info-name");
const infoHpEl       = document.getElementById("info-hp");
const infoAcEl       = document.getElementById("info-ac");
const infoPosEl      = document.getElementById("info-pos");
const infoStrEl      = document.getElementById("info-str");
const infoDexEl      = document.getElementById("info-dex");
const infoConEl      = document.getElementById("info-con");
const infoIntEl      = document.getElementById("info-int");
const infoWisEl      = document.getElementById("info-wis");
const infoChaEl      = document.getElementById("info-cha");

function updateInfoPanel(token) {
    if (!token) {
        infoPanel.classList.remove("visible");
        return;
    }
    const abs = token.abilities;
    infoNameEl.textContent = token.name;
    infoHpEl.textContent   = token.hp !== null ? `${token.hp} / ${token.maxHp}` : "—";
    infoAcEl.textContent   = token.ac !== null ? token.ac : "—";
    infoPosEl.textContent  = `${(token.x * CELL_FEET).toFixed(1)} ft, ${(token.y * CELL_FEET).toFixed(1)} ft`;
    infoStrEl.textContent  = abs ? abs.strength     : "—";
    infoDexEl.textContent  = abs ? abs.dexterity    : "—";
    infoConEl.textContent  = abs ? abs.constitution : "—";
    infoIntEl.textContent  = abs ? abs.intelligence : "—";
    infoWisEl.textContent  = abs ? abs.wisdom       : "—";
    infoChaEl.textContent  = abs ? abs.charisma     : "—";
    infoPanel.classList.add("visible");
}

function setActiveTool(tool) {
    activeTool = (activeTool === tool) ? null : tool;

    btnMove.classList.toggle("active",    activeTool === "move");
    btnMeasure.classList.toggle("active", activeTool === "measure");
    btnInfo.classList.toggle("active",    activeTool === "info");
    btnAction.classList.toggle("active",  activeTool === "action");

    measureReadout.classList.toggle("visible", activeTool === "measure");

    // Clean up any in-progress state when switching tools
    if (activeTool !== "measure") {
        measuring    = false;
        measureStart = null;
        measureEnd   = null;
    }
    if (activeTool !== "move") {
        draggingToken = null;
        hoveringToken = false;
    }
    if (activeTool !== "info") {
        infoHoveredToken = null;
        updateInfoPanel(null);
    }
    if (activeTool !== "action") {
        closeActionPanel();
    }

    draw();
    updateCursor();
}

btnMove.addEventListener("click",    () => setActiveTool("move"));
btnMeasure.addEventListener("click", () => setActiveTool("measure"));
btnInfo.addEventListener("click",    () => setActiveTool("info"));
btnAction.addEventListener("click",  () => setActiveTool("action"));

btnAddToken.addEventListener("click", () => {
    tokens.push(createToken());
    draw();
});

// End Turn button
const btnEndTurn = document.getElementById("btn-end-turn");
btnEndTurn.addEventListener("click", () => {
    wsSend({ type: "end_turn", seq: nextSeq() });
});

// ── WebSocket — combat session ─────────────────────────────────────────────

const wsStatusEl = document.getElementById("ws-status");
const ws = new WebSocket(`ws://${location.host}/ws/combat`);

let seqCounter = 0;
function nextSeq() { return ++seqCounter; }
function wsSend(obj) {
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

ws.onopen = () => {
    wsStatusEl.className = "ws-connected";
    wsStatusEl.title = "Connected";
};

ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    console.log("[combat ws]", msg);

    switch (msg.type) {
        case "connected":       break;  // already handled by onopen
        case "combat_started":  handleCombatStarted(msg); break;
        case "action_result":   handleActionResult(msg);  break;
        case "move_result":     handleMoveResult(msg);    break;
        case "turn_changed":    handleTurnChanged(msg);   break;
        case "combat_ended":    handleCombatEnded(msg);   break;
        case "error":           handleWsError(msg);       break;
        default:
            console.warn("[combat ws] unknown message type:", msg.type);
    }
};

ws.onclose = () => {
    wsStatusEl.className = "ws-disconnected";
    wsStatusEl.title = "Disconnected";
};

ws.onerror = () => {
    wsStatusEl.className = "ws-disconnected";
    wsStatusEl.title = "Connection error";
};

// ── WS message handlers ──────────────────────────────────────────────────────

function updateFromCombatState(state) {
    currentEntityId = state.current_entity_id;
    for (const es of state.entities) {
        const token = tokens.find(t => t.id === es.entity_id);
        if (!token) continue;
        token.hp    = es.hp;
        token.maxHp = es.max_hp;
        token.ac    = es.ac;
        token.x     = es.position.x;
        token.y     = es.position.y;
        token.resources = es.resources;
        token.alive     = es.alive;
    }
    draw();
}

function handleCombatStarted(msg) {
    // Remap frontend token IDs → backend entity IDs
    const idMap = msg.id_map;
    for (const token of tokens) {
        if (idMap[token.id]) {
            token.id = idMap[token.id];
        }
    }
    updateFromCombatState(msg.combat_state);
    console.log("[combat] started — initiative:", msg.initiative_order);
}

async function handleActionResult(msg) {
    // Play spell animation before applying state (so pre-damage positions are used)
    if (msg.action_type === "spell" && msg.animation && msg.animation.length > 0) {
        const casterToken = tokens.find(t => t.id === msg.attacker_id);
        const targetTokens = msg.results
            .map(r => tokens.find(t => t.id === r.target_id))
            .filter(Boolean);
        const context = {
            caster: casterToken ? { x: casterToken.x, y: casterToken.y } : { x: 0, y: 0 },
            targets: targetTokens.map(t => ({ x: t.x, y: t.y })),
            targetPoint: msg.target_point || null,
        };
        await animationManager.play(msg.animation, context);
    }

    updateFromCombatState(msg.combat_state);
    for (const line of (msg.log || [])) {
        console.log("[combat log]", line);
    }
}

function handleMoveResult(msg) {
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
}

// ── Send start_combat ─────────────────────────────────────────────────────────

function sendStartCombat() {
    const combatants = tokens
        .filter(t => t._creaturePath)
        .map(t => ({
            creature_path: t._creaturePath,
            team: t.team === 1 ? "ally" : t.team === 2 ? "enemy" : "neutral",
            position: { x: t.x, y: t.y },
            frontend_id: t.id,
        }));

    if (combatants.length >= 2) {
        wsSend({ type: "start_combat", seq: nextSeq(), combatants });
    }
}

// ── Spell resolution ──────────────────────────────────────────────────────────

async function fetchSpellsForToken(token) {
    if (token.spells.length === 0) return;
    const results = await Promise.all(
        token.spells.map(async (name) => {
            try {
                const r = await fetch(`/api/spells/by-name/${encodeURIComponent(name)}`);
                return r.ok ? r.json() : null;
            } catch { return null; }
        })
    );
    token.spellData = results.filter(Boolean);
}

// ── Init ──────────────────────────────────────────────────────────────────────

window.addEventListener("DOMContentLoaded", async () => {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
    camera.x = Math.floor(canvas.width  / 2);
    camera.y = Math.floor(canvas.height / 2);

    // Fetch creature data for the two combatants chosen on the setup page
    const c1Path = sessionStorage.getItem("creature_1");
    const c2Path = sessionStorage.getItem("creature_2");
    sessionStorage.removeItem("creature_1");
    sessionStorage.removeItem("creature_2");

    const fetchCreature = async (path) => {
        if (!path) return null;
        try {
            const r = await fetch(`/api/creatures/${path}`);
            return r.ok ? r.json() : null;
        } catch { return null; }
    };

    const [data1, data2] = await Promise.all([
        fetchCreature(c1Path),
        fetchCreature(c2Path),
    ]);

    if (data1) tokens.push(createToken(-3, 0, data1, 1, c1Path));
    if (data2) tokens.push(createToken( 3, 0, data2, 2, c2Path));

    // Resolve known_spells names → full spell objects for all tokens
    await Promise.all(tokens.map(fetchSpellsForToken));

    draw();

    // Bootstrap combat on the backend once the WS is ready
    if (ws.readyState === WebSocket.OPEN) {
        sendStartCombat();
    } else {
        ws.addEventListener("open", () => sendStartCombat(), { once: true });
    }
});
