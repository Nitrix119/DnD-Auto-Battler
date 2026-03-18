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

// ── Token registry ────────────────────────────────────────────────────────────
//
// Each token is a plain object representing a battlefield entity.
// `x` and `y` are the canonical world-space position in cell units — these are
// the values the move tool modifies and that will eventually sync with the
// backend Entity.position when the API layer is wired up.
//
// Future fields to add per token: name, hp, maxHp, ac, conditions, entityId, …

const tokens = [];

function createToken(x = 0.5, y = 0.5) {
    return {
        id:     crypto.randomUUID(),
        x,              // cell units — centre of token
        y,              // cell units — centre of token
        radius: 0.5,    // cell units — 0.5 cells = 5 ft diameter (standard creature)
    };
}

// ── Tool state ────────────────────────────────────────────────────────────────

let activeTool    = null;   // 'move' | 'measure' | null
let measuring     = false;
let measureStart  = null;   // { x, y } in cell units
let measureEnd    = null;   // { x, y } in cell units
let draggingToken = null;   // the token currently being dragged
let dragOffset    = { x: 0, y: 0 };  // cursor-to-centre offset at drag start
let hoveringToken = false;  // whether the cursor is over a draggable token

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

function drawTokens() {
    for (const token of tokens) {
        const { x: sx, y: sy } = worldToScreen(token.x, token.y);
        const sr = token.radius * CELL_PX * camera.zoom;
        const dragging = token === draggingToken;

        ctx.beginPath();
        ctx.arc(sx, sy, sr, 0, Math.PI * 2);
        ctx.fillStyle   = dragging ? "rgba(100, 180, 255, 0.70)" : "rgba(80, 140, 255, 0.50)";
        ctx.fill();
        ctx.strokeStyle = dragging ? "rgba(255, 255, 255, 1.00)" : "rgba(255, 255, 255, 0.80)";
        ctx.lineWidth   = dragging ? 2.0 : 1.5;
        ctx.stroke();
    }
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

    draw();
});

window.addEventListener("mouseup", (e) => {
    if (e.button === 0) {
        if (draggingToken) {
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
const btnAddToken    = document.getElementById("tool-add-token");
const measureReadout = document.getElementById("measure-readout");

function setActiveTool(tool) {
    activeTool = (activeTool === tool) ? null : tool;

    btnMove.classList.toggle("active",    activeTool === "move");
    btnMeasure.classList.toggle("active", activeTool === "measure");

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

    draw();
    updateCursor();
}

btnMove.addEventListener("click",    () => setActiveTool("move"));
btnMeasure.addEventListener("click", () => setActiveTool("measure"));

btnAddToken.addEventListener("click", () => {
    tokens.push(createToken());
    draw();
});

// ── WebSocket — combat session ─────────────────────────────────────────────
//
// One WebSocket per page load → one CombatSystem on the server.
// `ws` is module-level so future actions (move token, cast spell, end turn)
// can call ws.send(JSON.stringify({ type: "...", ... })) from anywhere.

const wsStatusEl = document.getElementById("ws-status");
const ws = new WebSocket(`ws://${location.host}/ws/combat`);

ws.onopen = () => {
    wsStatusEl.className = "ws-connected";
    wsStatusEl.title = "Connected";
};

ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    // Dispatch on msg.type — future server-push handling goes here.
    console.log("[combat ws]", msg);
};

ws.onclose = () => {
    wsStatusEl.className = "ws-disconnected";
    wsStatusEl.title = "Disconnected";
};

ws.onerror = () => {
    wsStatusEl.className = "ws-disconnected";
    wsStatusEl.title = "Connection error";
};

// ── Init ──────────────────────────────────────────────────────────────────────

window.addEventListener("DOMContentLoaded", () => {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
    camera.x = Math.floor(canvas.width  / 2);
    camera.y = Math.floor(canvas.height / 2);
    draw();
});
