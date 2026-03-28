// ── Entry point ───────────────────────────────────────────────────────────────
// Wires all modules together and bootstraps the combat session.

import { tokens, createToken, canvas, camera } from './state.js';
import { draw, resize } from './renderer.js';
import { initUIPanels, initBreakdownHovers } from './ui-panels.js';
import { wsSend, nextSeq, connectWS, whenOpen } from './websocket.js';
import { initInputHandlers } from './input.js';

// ── Session guard ─────────────────────────────────────────────────────────────
// The battle page is only valid when navigated to from the setup page.
// If the flag is absent (direct load, reload, back-button), redirect home.
// Imports are already resolved at this point; no WS or listeners set up yet.
if (!sessionStorage.getItem("combat_ready")) {
    location.replace("/");
    throw new Error("No active combat session — redirecting to setup.");
}
sessionStorage.removeItem("combat_ready");

// ── Module wiring ─────────────────────────────────────────────────────────────

// Inject wsSend/nextSeq into ui-panels so action buttons can send WS messages
// without ui-panels.js needing to import websocket.js (that would be circular).
initUIPanels({ wsSend, nextSeq });
initBreakdownHovers();
initInputHandlers();
window.addEventListener("resize", resize);

// Connect to the combat WebSocket immediately (matches original timing: before DOMContentLoaded)
connectWS();

// ── Spell fetching ────────────────────────────────────────────────────────────

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

// ── Combat start ──────────────────────────────────────────────────────────────

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

// ── Init ──────────────────────────────────────────────────────────────────────

window.addEventListener("DOMContentLoaded", async () => {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
    camera.x = Math.floor(canvas.width  / 2);
    camera.y = Math.floor(canvas.height / 2);

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

    await Promise.all(tokens.map(fetchSpellsForToken));

    draw();

    whenOpen(sendStartCombat);
});
