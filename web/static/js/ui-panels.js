// ── UI Panels ─────────────────────────────────────────────────────────────────
// All HTML DOM panel management: action panel, info panel, target panel,
// turn order bar, resource panel, cursor, and toolbar button state.

import {
    canvas, CELL_FEET, CURSOR_INFO, CURSOR_ACTION,
    tokens, state,
} from './state.js';
import { draw } from './renderer.js';

// Injected WS functions — set once by initUIPanels() to avoid a circular
// dependency (websocket.js imports us, so we cannot import websocket.js).
let _wsSend  = null;
let _nextSeq = null;

export function initUIPanels(deps) {
    _wsSend  = deps.wsSend;
    _nextSeq = deps.nextSeq;
}

// ── DOM element references ────────────────────────────────────────────────────

const btnMove        = document.getElementById("tool-move");
const btnMeasure     = document.getElementById("tool-measure");
const btnInfo        = document.getElementById("tool-info");
const btnAction      = document.getElementById("tool-action");

export const measureReadout = document.getElementById("measure-readout");
export const moveReadout    = document.getElementById("move-readout");

// Action panel
const actionPanel       = document.getElementById("action-panel");
const actionActorNameEl = document.getElementById("action-actor-name");
const actionListEl      = document.getElementById("action-list");

// Target panel
const targetPanel  = document.getElementById("target-panel");
const tgtNameEl    = document.getElementById("tgt-name");
const tgtHpEl      = document.getElementById("tgt-hp");
const tgtAcEl      = document.getElementById("tgt-ac");
export const tgtPosEl = document.getElementById("tgt-pos");
const tgtStrEl     = document.getElementById("tgt-str");
const tgtDexEl     = document.getElementById("tgt-dex");
const tgtConEl     = document.getElementById("tgt-con");
const tgtIntEl     = document.getElementById("tgt-int");
const tgtWisEl     = document.getElementById("tgt-wis");
const tgtChaEl     = document.getElementById("tgt-cha");

// Stat breakdown tooltip
const breakdownTooltip = document.getElementById("stat-breakdown-tooltip");

// Info panel
const infoPanel  = document.getElementById("info-panel");
const infoNameEl = document.getElementById("info-name");
const infoHpEl   = document.getElementById("info-hp");
const infoAcEl   = document.getElementById("info-ac");
export const infoPosEl = document.getElementById("info-pos");
const infoStrEl  = document.getElementById("info-str");
const infoDexEl  = document.getElementById("info-dex");
const infoConEl  = document.getElementById("info-con");
const infoIntEl  = document.getElementById("info-int");
const infoWisEl  = document.getElementById("info-wis");
const infoChaEl  = document.getElementById("info-cha");

// Targeting banner
const targetingBanner    = document.getElementById("targeting-banner");
const targetingLabelEl   = document.getElementById("targeting-label");
const targetingCancelBtn = document.getElementById("targeting-cancel");
targetingCancelBtn.addEventListener("click", () => setTargetingAction(null));

// Turn order bar
const turnOrderTrack = document.getElementById("turn-order-track");
const TOKEN_SIZE = 48;
const TOKEN_GAP  = 8;
const TOKEN_STEP = TOKEN_SIZE + TOKEN_GAP;

// Resource panel
const resourcePanel = document.getElementById("resource-panel");

const RES_ACTIVE_COLORS = {
    action:      "rgba(80, 210, 100, 0.95)",
    bonusAction: "rgba(255, 165, 50,  0.95)",
    reaction:    "rgba(175, 100, 255, 0.95)",
};
const RES_SPENT_COLOR = "rgba(110, 110, 110, 0.45)";

// ── Stat breakdown tooltip ────────────────────────────────────────────────────

export function showBreakdownTooltip(entries, label, anchorEl) {
    if (!entries || entries.length === 0) {
        hideBreakdownTooltip();
        return;
    }
    const total = entries.reduce((s, e) => s + e.value, 0);
    const nodes = [];

    const header = document.createElement("div");
    header.className = "breakdown-header";
    header.textContent = `${label}  ${total}`;
    nodes.push(header);

    const sep = document.createElement("div");
    sep.className = "breakdown-sep";
    nodes.push(sep);

    for (const entry of entries) {
        const sign = entry.value >= 0 ? "+" : "";
        const prefix = entry === entries[0] ? "" : sign;

        const row = document.createElement("div");
        row.className = "breakdown-row";

        const valSpan = document.createElement("span");
        valSpan.className = "breakdown-val";
        valSpan.textContent = `${prefix}${entry.value}`;

        const srcSpan = document.createElement("span");
        srcSpan.className = "breakdown-src";
        srcSpan.textContent = entry.source;

        row.appendChild(valSpan);
        row.appendChild(srcSpan);
        nodes.push(row);
    }

    breakdownTooltip.replaceChildren(...nodes);
    breakdownTooltip.classList.add("visible");

    const rect = anchorEl.getBoundingClientRect();
    breakdownTooltip.style.left  = "auto";
    breakdownTooltip.style.right = `${window.innerWidth - rect.right}px`;
    breakdownTooltip.style.top   = `${rect.bottom + 6}px`;
}

export function hideBreakdownTooltip() {
    breakdownTooltip.classList.remove("visible");
}

// Permanent listeners — set up once; read the current token at hover time.
export function initBreakdownHovers() {
    const infoAc = document.getElementById("info-ac");
    const tgtAc  = document.getElementById("tgt-ac");
    infoAc.addEventListener("mouseenter", () => {
        showBreakdownTooltip(state.infoHoveredToken?.statBreakdowns?.ac ?? [], "AC", infoAc);
    });
    infoAc.addEventListener("mouseleave", hideBreakdownTooltip);
    tgtAc.addEventListener("mouseenter", () => {
        showBreakdownTooltip(state.targetHovered?.statBreakdowns?.ac ?? [], "AC", tgtAc);
    });
    tgtAc.addEventListener("mouseleave", hideBreakdownTooltip);
}

// ── Target panel ──────────────────────────────────────────────────────────────

export function updateTargetPanel(token) {
    if (!token) {
        targetPanel.classList.remove("visible");
        hideBreakdownTooltip();
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
    tgtAcEl.classList.toggle("has-breakdown", !!(token.statBreakdowns?.ac?.length > 1));
    targetPanel.classList.add("visible");
}

// ── Targeting banner / action selection ──────────────────────────────────────

export function setTargetingAction(action) {
    state.targetingAction = action;
    for (const btn of actionListEl.querySelectorAll(".action-btn")) {
        btn.classList.toggle("active", btn._actionRef === action && action != null);
    }
    if (action) {
        targetingLabelEl.textContent = `Targeting: ${action.name}`;
        targetingBanner.classList.add("visible");
    } else {
        targetingBanner.classList.remove("visible");
        state.targetHovered = null;
        updateTargetPanel(null);
    }
}

// ── Action panel ──────────────────────────────────────────────────────────────

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

export function openActionPanel(token) {
    state.actionToken = token;
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
                btn._actionRef = action;
                btn.addEventListener("click", () => {
                    setTargetingAction(state.targetingAction === action ? null : action);
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
                btn._actionRef = spell;

                if (spell.spell_range?.type === "self") {
                    btn.title = "Self — instant cast";
                    btn.addEventListener("click", () => {
                        setTargetingAction(null);
                        _wsSend({
                            type: "cast_spell",
                            seq: _nextSeq(),
                            caster_id: token.backendId ?? token.id,
                            spell_name: spell.name,
                            target_ids: [token.backendId ?? token.id],
                        });
                    });
                } else {
                    btn.addEventListener("click", () => {
                        setTargetingAction(state.targetingAction === spell ? null : spell);
                    });
                }

                body.appendChild(btn);
            }
        }
    }));

    // ── Active Abilities ──────────────────────────────────────────────────────
    if (token.grantedActions.length > 0) {
        actionListEl.appendChild(makeActionSection("Active Abilities", (body) => {
            for (const action of token.grantedActions) {
                const btn = document.createElement("button");
                btn.className = "action-btn";
                btn.textContent = action.name;
                btn.dataset.actionName = action.name;
                btn._actionRef = action;
                btn.addEventListener("click", () => {
                    setTargetingAction(state.targetingAction === action ? null : action);
                });
                body.appendChild(btn);
            }
        }));
    }

    actionPanel.classList.add("visible");
}

export function closeActionPanel() {
    state.actionToken = null;
    setTargetingAction(null);
    actionPanel.classList.remove("visible");
}

// ── Info panel ────────────────────────────────────────────────────────────────

export function updateInfoPanel(token) {
    if (!token) {
        infoPanel.classList.remove("visible");
        hideBreakdownTooltip();
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
    infoAcEl.classList.toggle("has-breakdown", !!(token.statBreakdowns?.ac?.length > 1));
    infoPanel.classList.add("visible");
}

// ── Move readout ──────────────────────────────────────────────────────────────

export function refreshMoveReadout() {
    if (state.activeTool !== "move" || state.draggingToken) return;
    const token  = state.moveHoveredToken ?? tokens.find(t => (t.backendId ?? t.id) === state.currentEntityId);
    const moveFt = token?.resources?.movement ?? 0;
    moveReadout.textContent = `${(+moveFt).toFixed(1)} ft`;
    moveReadout.classList.remove("over-limit");
}

// ── Tool management ───────────────────────────────────────────────────────────

export function updateCursor() {
    if (state.panning) {
        canvas.style.cursor = "grabbing";
    } else if (state.activeTool === "move") {
        if (state.draggingToken)  canvas.style.cursor = "grabbing";
        else if (state.hoveringToken) canvas.style.cursor = "grab";
        else                canvas.style.cursor = "default";
    } else if (state.activeTool === "measure") {
        canvas.style.cursor = "crosshair";
    } else if (state.activeTool === "info") {
        canvas.style.cursor = CURSOR_INFO;
    } else if (state.activeTool === "action") {
        canvas.style.cursor = CURSOR_ACTION;
    } else {
        canvas.style.cursor = "";
    }
}

export function setActiveTool(tool) {
    state.activeTool = (state.activeTool === tool) ? null : tool;

    btnMove.classList.toggle("active",    state.activeTool === "move");
    btnMeasure.classList.toggle("active", state.activeTool === "measure");
    btnInfo.classList.toggle("active",    state.activeTool === "info");
    btnAction.classList.toggle("active",  state.activeTool === "action");

    measureReadout.classList.toggle("visible", state.activeTool === "measure");

    if (state.activeTool !== "measure") {
        state.measuring    = false;
        state.measureStart = null;
        state.measureEnd   = null;
    }
    if (state.activeTool !== "move") {
        state.draggingToken    = null;
        state.hoveringToken    = false;
        state.moveHoveredToken = null;
        state.dragStartPos     = null;
        moveReadout.classList.remove("visible");
    } else {
        refreshMoveReadout();
        moveReadout.classList.add("visible");
    }
    if (state.activeTool !== "info") {
        state.infoHoveredToken = null;
        updateInfoPanel(null);
    }
    if (state.activeTool !== "action") {
        closeActionPanel();
    }

    draw();
    updateCursor();
}

// ── Turn order bar ────────────────────────────────────────────────────────────

function _turnTokenColor(team) {
    if (team === "enemy")  return "rgba(180, 60, 60, 0.90)";
    if (team === "ally")   return "rgba(80, 140, 255, 0.90)";
    return "rgba(110, 110, 110, 0.90)";
}

function _turnTokenLabel(name) {
    return name.slice(0, 3).toUpperCase();
}

export function renderTurnOrderBar() {
    turnOrderTrack.innerHTML = "";
    for (let i = 0; i < state.turnOrderIds.length; i++) {
        const id   = state.turnOrderIds[i];
        const data = state.turnOrderEntityMap[id];
        if (!data) continue;
        const el = document.createElement("div");
        const classes = ["turn-token"];
        if (i === 0)       classes.push("active");
        if (!data.alive)   classes.push("dead");
        el.className        = classes.join(" ");
        el.dataset.entityId = id;
        el.style.background = _turnTokenColor(data.team);
        el.textContent      = _turnTokenLabel(data.name);
        el.title            = data.name;
        turnOrderTrack.appendChild(el);
    }
}

export async function updateTurnOrderBar(newIds, entities) {
    for (const e of entities) {
        state.turnOrderEntityMap[e.entity_id] = { name: e.name, team: e.team, alive: e.alive };
    }

    const oldFirst = state.turnOrderIds[0];
    const newFirst = newIds[0];
    const orderChanged = oldFirst !== undefined && oldFirst !== newFirst;

    if (!orderChanged || state.turnOrderAnimating) {
        state.turnOrderIds = newIds;
        renderTurnOrderBar();
        return;
    }

    // ── FLIP animation ───────────────────────────────────────────────────────
    const oldIndexMap = {};
    for (let i = 0; i < state.turnOrderIds.length; i++) {
        oldIndexMap[state.turnOrderIds[i]] = i;
    }

    state.turnOrderIds = newIds;
    renderTurnOrderBar();
    const newEls = Array.from(turnOrderTrack.querySelectorAll(".turn-token"));

    for (let j = 0; j < newEls.length; j++) {
        const el  = newEls[j];
        const eid = el.dataset.entityId;
        const oldIdx = oldIndexMap[eid];
        el.style.transition = "none";
        if (oldIdx === undefined) {
            el.style.transform = `translateX(${TOKEN_STEP}px)`;
            el.style.opacity   = "0";
        } else {
            el.style.transform = `translateX(${(oldIdx - j) * TOKEN_STEP}px)`;
        }
    }

    state.turnOrderAnimating = true;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));

    for (const el of newEls) {
        el.style.transition = "transform 0.35s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.30s ease";
        el.style.transform  = "";
        el.style.opacity    = "";
    }

    await new Promise(resolve => setTimeout(resolve, 380));
    state.turnOrderAnimating = false;
}

// ── Resource panel ────────────────────────────────────────────────────────────

function _resSvgAction(fill) {
    return `<svg class="res-icon" viewBox="0 0 24 24" width="22" height="22">`
         + `<circle cx="12" cy="12" r="9" fill="${fill}"/></svg>`;
}

function _resSvgBonus(fill) {
    return `<svg class="res-icon" viewBox="0 0 24 24" width="22" height="22">`
         + `<polygon points="12,3 21.5,20 2.5,20" fill="${fill}"/></svg>`;
}

function _resSvgReaction(fill) {
    return `<svg class="res-icon" viewBox="0 0 24 24" width="22" height="22">`
         + `<path d="M12,2 L14.5,9.5 L22,12 L14.5,14.5 L12,22 L9.5,14.5 L2,12 L9.5,9.5Z"`
         + ` fill="${fill}"/></svg>`;
}

function _resSlot(svgFn, count, colorKey) {
    const fill  = count > 0 ? RES_ACTIVE_COLORS[colorKey] : RES_SPENT_COLOR;
    const badge = count > 1 ? `\u00d7${count}` : "";
    return `<div class="res-slot">${svgFn(fill)}<span class="res-count">${badge}</span></div>`;
}

function _resMoveSlot(moveFt) {
    const color = moveFt > 0 ? "rgba(255,255,255,0.85)" : RES_SPENT_COLOR;
    return `<div class="res-slot res-slot-move">`
         + `<span class="res-move-text" style="color:${color}">${moveFt.toFixed(1)}&thinsp;ft</span>`
         + `<span class="res-count"></span>`
         + `</div>`;
}

function _buildResCard(token) {
    const r   = token.resources ?? {};
    const act = r.actions       ?? 0;
    const bon = r.bonus_actions  ?? 0;
    const rea = r.reactions     ?? 0;
    const mov = +(r.movement    ?? 0);

    const sep = `<div class="res-sep"></div>`;
    return `<div class="res-card">`
         + `<div class="res-card-name">${token.name}</div>`
         + `<div class="res-row">`
         + _resSlot(_resSvgAction,   act, "action")      + sep
         + _resSlot(_resSvgBonus,    bon, "bonusAction")  + sep
         + _resSlot(_resSvgReaction, rea, "reaction")     + sep
         + _resMoveSlot(mov)
         + `</div></div>`;
}

export function updateResourcePanel() {
    if (state.activeEntityIds.size === 0) {
        resourcePanel.classList.remove("visible");
        return;
    }
    const ordered = state.turnOrderIds.filter(id => state.activeEntityIds.has(id));
    let html = "";
    for (const id of ordered) {
        const token = tokens.find(t => (t.backendId ?? t.id) === id);
        if (token) html += _buildResCard(token);
    }
    resourcePanel.innerHTML = html;
    resourcePanel.classList.add("visible");
}
