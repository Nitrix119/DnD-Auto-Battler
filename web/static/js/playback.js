// ── Playback entry point ────────────────────────────────────────────────────
// Loads a match transcript and plays it back on the shared canvas renderer. Pure
// client-side: the only network call is fetching the (static) match file; there is
// no WebSocket and no engine. Reuses renderer.js + state.js unchanged.

import {
    tokens, camera, canvas,
    CELL_PX, CELL_FEET, ZOOM_MIN, ZOOM_MAX,
} from './state.js';
import { draw, resize, spawnFloatingLabel } from './renderer.js';
import { parseJsonl, buildSteps, boundsOf } from './playback-data.js';
import { createPlayer } from './playback-controls.js';

const DEFAULT_MATCH = '/static/matches/sample_match.jsonl';

// ── DOM handles ─────────────────────────────────────────────────────────────
const el = {
    round:    document.getElementById('pb-round'),
    desc:     document.getElementById('pb-desc'),
    panels:   document.getElementById('combatant-panels'),
    stepBack: document.getElementById('pb-step-back'),
    play:     document.getElementById('pb-play'),
    stepFwd:  document.getElementById('pb-step-fwd'),
    slider:   document.getElementById('pb-slider'),
    counter:  document.getElementById('pb-counter'),
    srcName:  document.getElementById('pb-source-name'),
    file:     document.getElementById('pb-file'),
};

// ── Per-match state ─────────────────────────────────────────────────────────
let steps = [];
let statBlocks = {};
let teamIndex = {};     // team string → 1 | 2 | 0 (token/card colour)
let cardRefs = {};      // entity id → { root, hpFill, hpText, pos, cond }
let player = null;

// ── Camera auto-fit (no pan/zoom input on this page) ────────────────────────
function fitCamera() {
    const b = boundsOf(steps);
    const pad = 1.5;                       // cells of breathing room
    const worldW = (b.maxX - b.minX) + pad * 2;
    const worldH = (b.maxY - b.minY) + pad * 2;
    const zoomX = canvas.width / (worldW * CELL_PX);
    const zoomY = canvas.height / (worldH * CELL_PX);
    const zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.min(zoomX, zoomY, 1.4)));
    camera.zoom = zoom;
    const cx = (b.minX + b.maxX) / 2;
    const cy = (b.minY + b.maxY) / 2;
    camera.x = canvas.width / 2 - cx * CELL_PX * zoom;
    camera.y = canvas.height / 2 - cy * CELL_PX * zoom;
}

// ── Combatant cards ─────────────────────────────────────────────────────────
const ABIL_ORDER = ['strength', 'dexterity', 'constitution', 'intelligence', 'wisdom', 'charisma'];
const ABIL_SHORT = { strength: 'STR', dexterity: 'DEX', constitution: 'CON', intelligence: 'INT', wisdom: 'WIS', charisma: 'CHA' };

function signed(n) { return n >= 0 ? `+${n}` : `${n}`; }

function abilitiesHtml(sb) {
    if (!sb?.abilities) return '';
    const cells = ABIL_ORDER.map((a) => {
        const ab = sb.abilities[a];
        if (!ab) return '';
        return `<div class="pb-ability"><div class="ab-name">${ABIL_SHORT[a]}</div>`
             + `<div class="ab-val">${ab.score} (${signed(ab.modifier)})</div></div>`;
    }).join('');
    return `<div class="pb-abilities">${cells}</div>`;
}

function optionsHtml(sb) {
    const acts = sb?.actions ?? [];
    const spells = sb?.known_spells ?? [];
    if (acts.length === 0 && spells.length === 0) return '';
    const rows = [];
    for (const a of acts) {
        const dmg = (a.damage ?? []).map((d) => d.formula).join(' + ');
        const rng = a.range_ft != null ? ` <span class="rng">${a.range_ft}ft</span>` : '';
        rows.push(`<div class="pb-option">⚔ ${a.name}${dmg ? ` (${dmg})` : ''}${rng}</div>`);
    }
    for (const s of spells) rows.push(`<div class="pb-option">✦ ${s}</div>`);
    return `<div class="pb-options"><span class="k">Options</span>${rows.join('')}</div>`;
}

function buildCards(step) {
    el.panels.innerHTML = '';
    cardRefs = {};
    const ents = Object.values(step.entities).sort(
        (a, b) => (teamIndex[a.team] - teamIndex[b.team]) || a.name.localeCompare(b.name),
    );
    for (const e of ents) {
        const sb = statBlocks[e.id];
        const ti = teamIndex[e.team] ?? 0;
        const root = document.createElement('div');
        root.className = `pb-card team-${ti}`;
        root.innerHTML =
            `<div class="pb-card-name"><span>${e.name}</span>`
          + `<span class="pb-card-team">Team ${e.team ?? '—'}</span></div>`
          + `<div class="pb-hpbar"><div class="pb-hpbar-fill"></div></div>`
          + `<div class="pb-stat-row"><span class="hp"></span><span><span class="k">AC</span> ${e.ac ?? '—'}</span></div>`
          + `<div class="pb-stat-row"><span class="k">POS</span><span class="pos"></span></div>`
          + `<div class="pb-stat-row cond-row"><span class="k">COND</span><span class="cond">—</span></div>`
          + abilitiesHtml(sb)
          + optionsHtml(sb);
        el.panels.appendChild(root);
        cardRefs[e.id] = {
            root,
            hpFill: root.querySelector('.pb-hpbar-fill'),
            hpText: root.querySelector('.hp'),
            pos: root.querySelector('.pos'),
            cond: root.querySelector('.cond'),
        };
    }
}

function updateCards(step) {
    for (const e of Object.values(step.entities)) {
        const ref = cardRefs[e.id];
        if (!ref) continue;
        const frac = e.maxHp ? Math.max(0, e.hp) / e.maxHp : 0;
        ref.hpFill.style.width = `${(frac * 100).toFixed(1)}%`;
        ref.hpFill.classList.toggle('crit', frac > 0 && frac <= 0.25);
        ref.hpFill.classList.toggle('low', frac > 0.25 && frac <= 0.5);
        ref.hpText.innerHTML = `<span class="k">HP</span> ${e.hp ?? '—'} / ${e.maxHp ?? '—'}`;
        ref.pos.textContent = `${e.cellX.toFixed(0)}, ${e.cellY.toFixed(0)}`;
        ref.cond.textContent = e.conditions.length ? e.conditions.join(', ') : '—';
        ref.root.classList.toggle('dead', !e.alive);
    }
}

// ── Token sync ──────────────────────────────────────────────────────────────
function syncTokens(step) {
    const seen = new Set();
    for (const e of Object.values(step.entities)) {
        seen.add(e.id);
        let tok = tokens.find((t) => t.id === e.id);
        if (!tok) {
            tok = { id: e.id };
            tokens.push(tok);
        }
        tok.x = e.cellX;
        tok.y = e.cellY;
        tok.name = e.name;
        tok.team = teamIndex[e.team] ?? 0;
        tok.radius = (e.sizeFt / CELL_FEET) / 2;
        tok.hp = e.hp;
        tok.maxHp = e.maxHp;
        tok.ac = e.ac;
        tok.dead = !e.alive;
    }
    // Drop any token no longer in the match (defensive; entities are stable here).
    for (let i = tokens.length - 1; i >= 0; i--) {
        if (!seen.has(tokens[i].id)) tokens.splice(i, 1);
    }
}

// ── Render one step ─────────────────────────────────────────────────────────
function renderStep(index, { direction } = { direction: 0 }) {
    const step = steps[index];
    if (!step) return;

    syncTokens(step);
    updateCards(step);

    el.round.textContent = step.round > 0 ? `Round ${step.round} · Turn ${step.turn}` : 'Setup';
    el.desc.textContent = step.caption;

    // One-shot damage/miss labels only when moving forward (not scrubbing back).
    if (step.fx && direction === 1) {
        const t = step.entities[step.fx.targetId];
        if (t) spawnFloatingLabel(t.cellX, t.cellY, step.fx.text, step.fx.hit);
    }

    el.slider.value = String(index);
    el.counter.textContent = `${index + 1} / ${steps.length}`;
    draw();
}

function onPlayerState({ playing, atStart, atEnd }) {
    el.play.textContent = playing ? '⏸' : '▶';
    el.stepBack.disabled = atStart && !playing;
    el.stepFwd.disabled = atEnd && !playing;
}

// ── Load a match (default fetch or file-picker) ─────────────────────────────
function loadMatch(text, sourceName) {
    const records = parseJsonl(text);
    const built = buildSteps(records);
    steps = built.steps;
    statBlocks = built.statBlocks;

    // Assign colour indices to the (up to two) teams, in a stable order.
    teamIndex = {};
    const teamNames = Object.keys(built.teams);
    if (teamNames.length === 0) {
        for (const e of Object.values(steps[0]?.entities ?? {})) {
            if (!(e.team in teamIndex)) teamIndex[e.team] = Object.keys(teamIndex).length + 1;
        }
    } else {
        teamNames.forEach((name, i) => { teamIndex[name] = i < 2 ? i + 1 : 0; });
    }

    el.srcName.textContent = sourceName;
    el.slider.max = String(Math.max(0, steps.length - 1));

    buildCards(steps[0]);
    fitCamera();

    player = createPlayer({
        stepCount: steps.length,
        onStep: renderStep,
        onStateChange: onPlayerState,
    });
    renderStep(0, { direction: 0 });
    player.emitState();
}

async function loadDefault() {
    try {
        const r = await fetch(DEFAULT_MATCH);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        loadMatch(await r.text(), DEFAULT_MATCH.split('/').pop());
    } catch (err) {
        el.desc.textContent = `Could not load ${DEFAULT_MATCH} — use “Open…” to pick a file. (${err.message})`;
    }
}

// ── Wiring ──────────────────────────────────────────────────────────────────
function initCanvas() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
}

el.stepBack.addEventListener('click', () => player?.stepBackward());
el.stepFwd.addEventListener('click', () => player?.stepForward());
el.play.addEventListener('click', () => player?.toggle());
el.slider.addEventListener('input', (e) => player?.seek(e.target.value));

el.file.addEventListener('change', async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    loadMatch(await file.text(), file.name);
});

window.addEventListener('keydown', (e) => {
    if (!player) return;
    if (e.key === 'ArrowRight') { e.preventDefault(); player.stepForward(); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); player.stepBackward(); }
    else if (e.key === ' ') { e.preventDefault(); player.toggle(); }
});

window.addEventListener('resize', () => {
    resize();          // resizes canvas + redraws
    if (steps.length) { fitCamera(); renderStep(player ? player.index : 0, { direction: 0 }); }
});

initCanvas();
loadDefault();
