// ── Shared State ──────────────────────────────────────────────────────────────
// Single source of truth for all constants and mutable state.
// Every other module imports from here; nothing imports into this file.

export const canvas = document.getElementById("grid");
export const ctx    = canvas.getContext("2d");

// Camera state: x/y are the screen-space offset of world origin (0,0)
export const camera = { x: 0, y: 0, zoom: 1.0 };

export const CELL_PX    = 50;    // base cell size in pixels at zoom 1 (1 cell = 5 ft)
export const CELL_FEET  = 5;     // feet per grid cell — keep in sync with CELL_FEET in web/routers/combat.py
export const ZOOM_MIN   = 0.10;
export const ZOOM_MAX   = 8.0;
export const ZOOM_SPEED = 0.001;

// Colours
export const COLOR_GRID  = "rgba(255, 255, 255, 0.07)";
export const COLOR_LABEL = "rgba(255, 255, 255, 0.25)";

// Custom cursor for the info tool — magnifying glass built from an inline SVG
export const CURSOR_INFO = (() => {
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20">'
              + '<circle cx="8" cy="8" r="5" fill="none" stroke="white" stroke-width="1.5"/>'
              + '<line x1="12" y1="12" x2="17" y2="17" stroke="white" stroke-width="1.8" stroke-linecap="round"/>'
              + '</svg>';
    return `url('data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}') 8 8, zoom-in`;
})();

// Custom cursor for the action tool — lightning bolt
export const CURSOR_ACTION = (() => {
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20">'
              + '<polygon points="11,1 4,11 10,11 9,19 16,9 10,9" fill="white" opacity="0.9"/>'
              + '</svg>';
    return `url('data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}') 10 10, crosshair`;
})();

// ── Token registry ────────────────────────────────────────────────────────────
//
// D&D 5e size → token radius in cell units (1 cell = 5 ft).
// Radius = half the creature's space, so the circle fills its occupied squares.
export const SIZE_RADIUS = {
    tiny:        0.25,
    small:       0.5,
    medium:      0.5,
    large:       1.0,
    huge:        1.5,
    gargantuan:  2.0,
};

export const tokens = [];

export function createToken(x = 0.5, y = 0.5, creatureData = null, team = 0, creaturePath = null) {
    const size   = creatureData?.size?.toLowerCase() ?? "medium";
    const radius = SIZE_RADIUS[size] ?? SIZE_RADIUS.medium;
    return {
        id:        crypto.randomUUID(),
        _creaturePath: creaturePath,
        x,
        y,
        radius,
        team,
        name:      creatureData?.name           ?? "Token",
        hp:        creatureData?.hit_points     ?? null,
        maxHp:     creatureData?.hit_points_max ?? null,
        ac:        creatureData?.armor_class    ?? null,
        abilities: creatureData?.abilities      ?? null,
        actions:   creatureData?.actions        ?? [],
        spells:    creatureData?.known_spells   ?? [],
        spellData: [],
        grantedActions: [],
    };
}

// ── Mutable state ─────────────────────────────────────────────────────────────
//
// All mutable flags live on a single exported object so any module can write
// them via property assignment (e.g. state.draggingToken = t).
// ES module live bindings only propagate updates for the declaring module, so
// bare `let` exports would not be writable from other modules.
export const state = {
    // Tool
    activeTool:       null,   // 'move' | 'measure' | 'info' | 'action' | null

    // Measure tool
    measuring:        false,
    measureStart:     null,   // { x, y } in cell units
    measureEnd:       null,   // { x, y } in cell units

    // Move / drag
    draggingToken:    null,
    dragOffset:       { x: 0, y: 0 },
    dragStartPos:     null,   // { x, y } at drag start
    dragStartMovement: 0,     // movement remaining (ft) at drag start
    pendingMoveToken: null,   // token whose move was sent (for snap-back)
    pendingMovePos:   null,   // pre-move position to restore on rejection
    moveHoveredToken: null,
    hoveringToken:    false,

    // Info / action / targeting
    infoHoveredToken: null,
    actionToken:      null,
    targetingAction:  null,
    targetHovered:    null,

    // Session
    currentEntityId:  null,
    activeEntityIds:  new Set(),

    // Pan / zoom input
    panning:          false,
    panLast:          { x: 0, y: 0 },
    cursorWorld:      { x: 0, y: 0 },

    // Turn order
    turnOrderIds:        [],
    turnOrderEntityMap:  {},
    turnOrderAnimating:  false,

    // Floating labels animation loop
    floatingLabels:   [],
    _floatLoopRunning: false,
};
