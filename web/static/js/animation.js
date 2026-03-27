// ── Spell Animation Engine ───────────────────────────────────────────────────
// Data-driven animation system for spell visual effects.
// Animations are defined in spell JSON files as arrays of phases,
// each phase containing effects that play in parallel.
//
// Depends on battle.js globals: ctx, camera, CELL_PX, worldToScreen, draw

// ── Location Resolution ─────────────────────────────────────────────────────

function resolveLocation(ref, context) {
    switch (ref) {
        case "caster":       return context.caster;
        case "target":       return context.targets[0] || context.caster;
        case "target_point": return context.targetPoint || context.targets[0] || context.caster;
        case "caster_edge": {
            // Edge of the caster's token in the direction of the primary target/point.
            const toward = context.targetPoint || context.targets[0] || null;
            const r = context.casterRadius || 0;
            if (!toward || r === 0) return context.caster;
            const dx = toward.x - context.caster.x;
            const dy = toward.y - context.caster.y;
            const len = Math.sqrt(dx * dx + dy * dy);
            if (len < 0.0001) return context.caster;
            return { x: context.caster.x + (dx / len) * r, y: context.caster.y + (dy / len) * r };
        }
        default:
            if (context._resolvedAt) return context._resolvedAt;
            console.warn(`[animation] Unknown location ref: "${ref}"`);
            return context.caster;
    }
}

// ── Effect Registry ─────────────────────────────────────────────────────────

const EFFECT_REGISTRY = {};

function registerEffect(type, factory) {
    EFFECT_REGISTRY[type] = factory;
}

function createEffects(effectDef, context) {
    const factory = EFFECT_REGISTRY[effectDef.type];
    if (!factory) {
        console.warn(`[animation] Unknown effect type: "${effectDef.type}"`);
        return [{ _startTime: null, update() {}, render() {}, isComplete() { return true; } }];
    }
    // "each_target" expansion: duplicate the effect for every target
    if (effectDef.at === "each_target") {
        return context.targets.map(t => {
            const subCtx = { ...context, _resolvedAt: t };
            return factory(effectDef, subCtx);
        });
    }
    return [factory(effectDef, context)];
}

// ── Helper: parse hex color to {r,g,b} ──────────────────────────────────────

function hexToRgb(hex) {
    const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
    if (!m) return { r: 255, g: 255, b: 255 };
    return { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) };
}

function rgba(hex, alpha) {
    const { r, g, b } = hexToRgb(hex);
    return `rgba(${r},${g},${b},${Math.max(0, Math.min(1, alpha))})`;
}

// ── Effect Implementations ──────────────────────────────────────────────────

// Projectile: glowing mote traveling from A to B with optional trail
registerEffect("projectile", (def, ctx) => {
    const from = resolveLocation(def.from || "caster", ctx);
    const to = resolveLocation(def.to || "target", ctx);
    const speed = def.speed || 5;            // cells per second
    const size = def.size || 4;              // px radius at zoom 1
    const showTrail = def.trail !== false;
    const trailLen = def.trail_length || 8;
    const baseOpacity = def.opacity ?? 1.0;

    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const distCells = Math.sqrt(dx * dx + dy * dy);
    const durationMs = (distCells / speed) * 1000;
    const trail = [];

    return {
        _startTime: null,
        _progress: 0,
        update(ts) {
            this._progress = Math.min(1, (ts - this._startTime) / Math.max(durationMs, 1));
            const cx = from.x + dx * this._progress;
            const cy = from.y + dy * this._progress;
            if (showTrail) {
                trail.push({ x: cx, y: cy });
                while (trail.length > trailLen) trail.shift();
            }
            this._cx = cx;
            this._cy = cy;
        },
        render(c) {
            // Trail
            if (showTrail) {
                for (let i = 0; i < trail.length; i++) {
                    const alpha = (i / trail.length) * 0.5 * baseOpacity;
                    const { x: sx, y: sy } = worldToScreen(trail[i].x, trail[i].y);
                    const sr = size * camera.zoom * (0.4 + 0.6 * i / trail.length);
                    c.beginPath();
                    c.arc(sx, sy, sr, 0, Math.PI * 2);
                    c.fillStyle = rgba(def.color, alpha);
                    c.fill();
                }
            }
            // Main mote
            const { x: sx, y: sy } = worldToScreen(this._cx, this._cy);
            const sr = size * camera.zoom;
            // Glow
            c.beginPath();
            c.arc(sx, sy, sr * 2, 0, Math.PI * 2);
            c.fillStyle = rgba(def.color, 0.15 * baseOpacity);
            c.fill();
            // Core
            c.beginPath();
            c.arc(sx, sy, sr, 0, Math.PI * 2);
            c.fillStyle = rgba(def.color, baseOpacity);
            c.fill();
        },
        isComplete() { return this._progress >= 1; },
    };
});

// Expanding Ring: circle expanding outward from a point
registerEffect("expanding_ring", (def, ctx) => {
    const at = resolveLocation(def.at || "target_point", ctx);
    const radiusFt = def.radius || 20;
    const radiusCells = radiusFt / 5;        // 1 cell = 5 ft
    const speed = def.speed || 3;            // cells per second
    const lineWidth = def.line_width || 3;
    const fill = def.fill || false;
    const baseOpacity = def.opacity ?? 1.0;
    const durationMs = (radiusCells / speed) * 1000;

    return {
        _startTime: null,
        _progress: 0,
        update(ts) {
            this._progress = Math.min(1, (ts - this._startTime) / Math.max(durationMs, 1));
        },
        render(c) {
            const { x: sx, y: sy } = worldToScreen(at.x, at.y);
            const currentRadius = radiusCells * this._progress * CELL_PX * camera.zoom;
            const fadeAlpha = baseOpacity * (1 - this._progress * 0.5);

            if (fill) {
                c.beginPath();
                c.arc(sx, sy, currentRadius, 0, Math.PI * 2);
                c.fillStyle = rgba(def.color, fadeAlpha * 0.2);
                c.fill();
            }
            c.beginPath();
            c.arc(sx, sy, currentRadius, 0, Math.PI * 2);
            c.strokeStyle = rgba(def.color, fadeAlpha);
            c.lineWidth = lineWidth * camera.zoom;
            c.stroke();
        },
        isComplete() { return this._progress >= 1; },
    };
});

// Expanding Cone: a triangle that expands outward from a point in a direction,
// matching D&D's 1:2 width-to-length cone ratio (tan(half_angle) = 0.5).
// Direction is derived from `from` → `to`, like beam.
registerEffect("expanding_cone", (def, ctx) => {
    const from = resolveLocation(def.from || "caster", ctx);
    const dirTarget = def.to
        ? resolveLocation(def.to, ctx)
        : (ctx.targetPoint || ctx.targets[0] || from);

    const distanceFt = def.distance_ft || 30;
    const distanceCells = distanceFt / 5;
    const speed = def.speed || 3;            // cells per second
    const lineWidth = def.line_width || 3;
    const fill = def.fill || false;
    const baseOpacity = def.opacity ?? 1.0;
    const durationMs = (distanceCells / speed) * 1000;

    // D&D cone: at any distance d, the half-width is d/2, so tan(half_angle) = 0.5
    const TAN_HALF = 0.5;

    const ddx = dirTarget.x - from.x;
    const ddy = dirTarget.y - from.y;
    const len = Math.sqrt(ddx * ddx + ddy * ddy);
    const dirAngle = len > 0.0001 ? Math.atan2(ddy, ddx) : 0;

    return {
        _startTime: null,
        _progress: 0,
        update(ts) {
            this._progress = Math.min(1, (ts - this._startTime) / Math.max(durationMs, 1));
        },
        render(c) {
            const currentLenPx = distanceCells * this._progress * CELL_PX * camera.zoom;
            const halfWidthPx = currentLenPx * TAN_HALF;
            const { x: ox, y: oy } = worldToScreen(from.x, from.y);
            const cosD = Math.cos(dirAngle);
            const sinD = Math.sin(dirAngle);

            // Front-centre of the cone face
            const fx = ox + cosD * currentLenPx;
            const fy = oy + sinD * currentLenPx;
            // Left and right far corners (perpendicular to direction)
            const lx = fx - sinD * halfWidthPx;
            const ly = fy + cosD * halfWidthPx;
            const rx = fx + sinD * halfWidthPx;
            const ry = fy - cosD * halfWidthPx;

            const fadeAlpha = baseOpacity * (1 - this._progress * 0.5);

            c.beginPath();
            c.moveTo(ox, oy);
            c.lineTo(lx, ly);
            c.lineTo(rx, ry);
            c.closePath();

            if (fill) {
                c.fillStyle = rgba(def.color, fadeAlpha * 0.2);
                c.fill();
            }
            c.strokeStyle = rgba(def.color, fadeAlpha);
            c.lineWidth = lineWidth * camera.zoom;
            c.stroke();
        },
        isComplete() { return this._progress >= 1; },
    };
});

// Flash: bright circle that fades out on a target
registerEffect("flash", (def, ctx) => {
    const at = resolveLocation(def.at || "target", ctx);
    const duration = (def.duration || 0.3) * 1000;
    const sizeMult = def.size || 1.0;
    const baseOpacity = def.opacity ?? 1.0;

    return {
        _startTime: null,
        _progress: 0,
        update(ts) {
            this._progress = Math.min(1, (ts - this._startTime) / Math.max(duration, 1));
        },
        render(c) {
            const { x: sx, y: sy } = worldToScreen(at.x, at.y);
            const radius = sizeMult * 0.5 * CELL_PX * camera.zoom;
            const alpha = baseOpacity * (1 - this._progress);

            // Outer glow
            c.beginPath();
            c.arc(sx, sy, radius * 1.5, 0, Math.PI * 2);
            c.fillStyle = rgba(def.color, alpha * 0.3);
            c.fill();
            // Core flash
            c.beginPath();
            c.arc(sx, sy, radius, 0, Math.PI * 2);
            c.fillStyle = rgba(def.color, alpha);
            c.fill();
        },
        isComplete() { return this._progress >= 1; },
    };
});

// Aura: pulsing glow around a token
registerEffect("aura", (def, ctx) => {
    const at = resolveLocation(def.at || "caster", ctx);
    const duration = (def.duration || 1.0) * 1000;
    const sizeMult = def.size || 1.5;
    const pulses = def.pulses || 2;
    const baseOpacity = def.opacity ?? 0.6;

    return {
        _startTime: null,
        _progress: 0,
        update(ts) {
            this._progress = Math.min(1, (ts - this._startTime) / Math.max(duration, 1));
        },
        render(c) {
            const { x: sx, y: sy } = worldToScreen(at.x, at.y);
            const radius = sizeMult * 0.5 * CELL_PX * camera.zoom;
            // Pulse: sine wave for pulsing, fade out toward end
            const pulse = Math.sin(this._progress * pulses * Math.PI * 2) * 0.5 + 0.5;
            const fadeOut = 1 - Math.max(0, (this._progress - 0.7) / 0.3);
            const alpha = baseOpacity * pulse * fadeOut;

            c.beginPath();
            c.arc(sx, sy, radius * (0.8 + 0.2 * pulse), 0, Math.PI * 2);
            c.fillStyle = rgba(def.color, alpha * 0.3);
            c.fill();
            c.beginPath();
            c.arc(sx, sy, radius * 0.7 * (0.8 + 0.2 * pulse), 0, Math.PI * 2);
            c.fillStyle = rgba(def.color, alpha * 0.6);
            c.fill();
        },
        isComplete() { return this._progress >= 1; },
    };
});

// Particles: burst of small dots scattering outward
registerEffect("particles", (def, ctx) => {
    const at = resolveLocation(def.at || "target_point", ctx);
    const count = def.count || 20;
    const spreadFt = def.spread || 20;
    const spreadCells = spreadFt / 5;
    const duration = (def.duration || 0.8) * 1000;
    const speed = def.speed || 2;
    const baseOpacity = def.opacity ?? 1.0;

    // Pre-generate particle directions
    const particles = [];
    for (let i = 0; i < count; i++) {
        const angle = Math.random() * Math.PI * 2;
        const dist = 0.3 + Math.random() * 0.7; // normalized distance factor
        particles.push({
            angle,
            dist,
            size: 1 + Math.random() * 2,
        });
    }

    return {
        _startTime: null,
        _progress: 0,
        update(ts) {
            this._progress = Math.min(1, (ts - this._startTime) / Math.max(duration, 1));
        },
        render(c) {
            const alpha = baseOpacity * (1 - this._progress);
            for (const p of particles) {
                const r = spreadCells * p.dist * this._progress * speed;
                const px = at.x + Math.cos(p.angle) * r;
                const py = at.y + Math.sin(p.angle) * r;
                const { x: sx, y: sy } = worldToScreen(px, py);
                const sr = p.size * camera.zoom;
                c.beginPath();
                c.arc(sx, sy, sr, 0, Math.PI * 2);
                c.fillStyle = rgba(def.color, alpha);
                c.fill();
            }
        },
        isComplete() { return this._progress >= 1; },
    };
});

// Beam: line between two points that appears and fades
// Special `to` value: "direction_endpoint" — requires def.distance_ft.
// Computes an endpoint at that distance (in feet) from `from`, in the
// direction of targetPoint (or first target).
registerEffect("beam", (def, ctx) => {
    const from = resolveLocation(def.from || "caster", ctx);
    let to;
    if (def.to === "direction_endpoint" && def.distance_ft != null) {
        const dirTarget = ctx.targetPoint || ctx.targets[0] || from;
        const dx = dirTarget.x - from.x;
        const dy = dirTarget.y - from.y;
        const len = Math.sqrt(dx * dx + dy * dy);
        if (len > 0.0001) {
            const distCells = def.distance_ft / 5;
            to = { x: from.x + (dx / len) * distCells, y: from.y + (dy / len) * distCells };
        } else {
            to = from;
        }
    } else {
        to = resolveLocation(def.to || "target", ctx);
    }
    const duration = (def.duration || 0.4) * 1000;
    const width = def.width || 3;
    const baseOpacity = def.opacity ?? 1.0;

    return {
        _startTime: null,
        _progress: 0,
        update(ts) {
            this._progress = Math.min(1, (ts - this._startTime) / Math.max(duration, 1));
        },
        render(c) {
            const alpha = baseOpacity * (1 - this._progress * 0.7);
            const { x: x1, y: y1 } = worldToScreen(from.x, from.y);
            const { x: x2, y: y2 } = worldToScreen(to.x, to.y);

            // Glow
            c.beginPath();
            c.moveTo(x1, y1);
            c.lineTo(x2, y2);
            c.strokeStyle = rgba(def.color, alpha * 0.3);
            c.lineWidth = (width * 3) * camera.zoom;
            c.stroke();
            // Core
            c.beginPath();
            c.moveTo(x1, y1);
            c.lineTo(x2, y2);
            c.strokeStyle = rgba(def.color, alpha);
            c.lineWidth = width * camera.zoom;
            c.stroke();
        },
        isComplete() { return this._progress >= 1; },
    };
});

// ── Animation Sequence ──────────────────────────────────────────────────────
// Manages playing through phases for a single spell cast.

class AnimationSequence {
    constructor(phaseDefs, context, onComplete) {
        this._phaseDefs = phaseDefs;
        this._context = context;
        this._onComplete = onComplete;
        this._currentPhaseIndex = -1;
        this._activeEffects = [];
        this._complete = false;
    }

    start() {
        this._advancePhase();
    }

    _advancePhase() {
        this._currentPhaseIndex++;
        if (this._currentPhaseIndex >= this._phaseDefs.length) {
            this._complete = true;
            return;
        }
        const phaseDef = this._phaseDefs[this._currentPhaseIndex];
        this._activeEffects = phaseDef.flatMap(effectDef =>
            createEffects(effectDef, this._context)
        );
    }

    update(timestamp, canvasCtx) {
        if (this._complete) return;
        for (const effect of this._activeEffects) {
            if (!effect._startTime) effect._startTime = timestamp;
            effect.update(timestamp);
            effect.render(canvasCtx);
        }
        if (this._activeEffects.every(e => e.isComplete())) {
            this._advancePhase();
        }
    }

    isComplete() { return this._complete; }

    finish() {
        if (this._onComplete) this._onComplete();
    }
}

// ── Animation Manager (singleton) ───────────────────────────────────────────

class AnimationManager {
    constructor() {
        this._active = null;
        this._queue = [];
    }

    /**
     * Play a spell animation.
     * @param {Array<Array<Object>>} phases - animation definition from spell JSON
     * @param {Object} context - { caster: {x,y}, targets: [{x,y},...], targetPoint: {x,y}|null }
     * @returns {Promise<void>} resolves when all phases complete
     */
    play(phases, context) {
        if (!phases || phases.length === 0) return Promise.resolve();
        return new Promise(resolve => {
            const seq = new AnimationSequence(phases, context, resolve);
            if (!this._active) {
                this._active = seq;
                this._active.start();
                _startAnimationLoop();
            } else {
                this._queue.push(seq);
            }
        });
    }

    update(timestamp) {
        if (!this._active) return;
        this._active.update(timestamp, ctx);
        if (this._active.isComplete()) {
            this._active.finish();
            this._active = this._queue.shift() || null;
            if (this._active) {
                this._active.start();
            }
        }
    }

    hasActiveAnimations() {
        return this._active !== null;
    }
}

// ── On-Demand Animation Loop ────────────────────────────────────────────────
// Only runs requestAnimationFrame while animations are playing.

let _animLoopRunning = false;

function _startAnimationLoop() {
    if (_animLoopRunning) return;
    _animLoopRunning = true;
    requestAnimationFrame(_animationTick);
}

function _animationTick(timestamp) {
    if (!animationManager.hasActiveAnimations()) {
        _animLoopRunning = false;
        draw();  // final clean frame
        return;
    }
    draw();                          // redraw base scene
    animationManager.update(timestamp);  // draw effects on top
    requestAnimationFrame(_animationTick);
}

// ── Export singleton ────────────────────────────────────────────────────────

const animationManager = new AnimationManager();
