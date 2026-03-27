# Spell Animation Guide

Animations are defined directly inside spell JSON files and drive all visual effects on the front-end canvas. The engine is data-driven: no JavaScript changes are needed to add new animations — only JSON.

**Source:** [web/static/js/animation.js](../../web/static/js/animation.js)

---

## Structure

An animation is a nested array assigned to the `"animation"` key in a spell JSON file:

```json
"animation": [
  [ <effect>, <effect> ],
  [ <effect> ],
  [ <effect>, <effect> ]
]
```

- The outer array is a list of **phases**.
- Each phase is an array of **effects**.
- Effects within the same phase play **in parallel**.
- Phases play **sequentially** — the next phase begins only after every effect in the current phase has finished.

```json
"animation": [
  [{"type": "projectile", "color": "#FF4400", "from": "caster", "to": "target_point", "speed": 12}],
  [
    {"type": "expanding_ring", "color": "#FF6600", "at": "target_point", "radius": 20, "speed": 8, "fill": true},
    {"type": "particles", "color": "#FF2200", "at": "target_point", "count": 40, "spread": 30, "duration": 0.6}
  ],
  [{"type": "flash", "color": "#FF4400", "at": "each_target", "duration": 0.3}]
]
```

The example above (Fireball) shows a three-phase animation:
1. A projectile travels to the impact point.
2. An expanding ring *and* a particle burst both play at the same time.
3. A flash appears on each creature caught in the blast.

---

## Location References

Most effects have a position field (`at`, `from`, or `to`) that accepts one of these string values:

| Value | Meaning |
|---|---|
| `"caster"` | The caster's grid position |
| `"target"` | The first target's position (falls back to caster if no targets) |
| `"target_point"` | The explicit AOE center point (falls back to first target, then caster) |
| `"caster_edge"` | The edge of the caster's token, in the direction of the primary target or target point. Requires `casterRadius` to be set on the token. |
| `"direction_endpoint"` | **`beam` only.** Extends from `from` in the direction of the primary target or target point, by `distance_ft` feet. |
| `"each_target"` | **Special expansion.** Duplicates the effect once per target. See below. |

### `"each_target"` expansion

When you set `at` to `"each_target"`, the engine automatically creates one copy of that effect for every creature in the target list. This is the standard way to show individual hit effects on AOE spells.

```json
{"type": "flash", "color": "#FF4400", "at": "each_target", "duration": 0.3}
```

This only works on the `at` field of point-based effects (`flash`, `aura`, `particles`). It does not apply to `from`/`to` fields.

---

## Effect Types

### `projectile`

A glowing mote that travels from one location to another, with an optional fading trail.

```json
{"type": "projectile", "color": "#FF4400", "from": "caster", "to": "target", "speed": 8, "size": 3, "trail": true}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `color` | hex string | — | Fill color of the mote and trail, e.g. `"#FF4400"` |
| `from` | location ref | `"caster"` | Origin of the projectile |
| `to` | location ref | `"target"` | Destination of the projectile |
| `speed` | number | `5` | Travel speed in **cells per second**. Duration is computed from distance divided by speed. |
| `size` | number | `4` | Radius of the mote in pixels at zoom 1. The glow halo is twice this radius at 15% opacity. |
| `trail` | boolean | `true` | Whether to render a fading particle trail behind the mote |
| `trail_length` | number | `8` | Number of trail positions to keep. Higher values produce a longer tail. |
| `opacity` | number | `1.0` | Master opacity for both the mote and the trail (0–1) |

**Notes:**
- Duration is automatic — it is computed from the distance between `from` and `to` divided by `speed`. You do not set a `duration` on a projectile.
- To launch three simultaneous darts (Magic Missile), place three projectile effects in the same phase with different speeds:

```json
[
  {"type": "projectile", "color": "#9999FF", "from": "caster", "to": "target", "speed": 10, "size": 2},
  {"type": "projectile", "color": "#AAAAFF", "from": "caster", "to": "target", "speed": 8,  "size": 2},
  {"type": "projectile", "color": "#BBBBFF", "from": "caster", "to": "target", "speed": 6,  "size": 2}
]
```

---

### `expanding_ring`

A circle that expands outward from a point at a fixed speed, typically used for area-of-effect bursts. The ring fades out as it expands. If `fill` is true, the interior is also filled at a low opacity.

```json
{"type": "expanding_ring", "color": "#FF6600", "at": "target_point", "radius": 20, "speed": 8, "fill": true}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `color` | hex string | — | Color of the ring stroke and optional fill |
| `at` | location ref | `"target_point"` | Center point of the expanding ring |
| `radius` | number | `20` | Maximum radius in **feet**. Converted to grid cells internally (1 cell = 5 ft). |
| `speed` | number | `3` | Expansion speed in **cells per second**. Duration is computed from `radius / speed`. |
| `line_width` | number | `3` | Stroke width of the ring outline in pixels at zoom 1 |
| `fill` | boolean | `false` | If true, fills the interior with the color at 20% opacity |
| `opacity` | number | `1.0` | Master opacity that fades to 50% of its initial value as the ring reaches full size |

**Notes:**
- Duration is automatic — the ring expands until it reaches `radius` at `speed`.
- Set `radius` to match the AOE size of the spell (e.g. `20` for a 20-ft radius Fireball, `15` for Burning Hands' 15-ft cone, `60` for Cone of Cold).
- Use `"at": "caster"` for self-originating cones and cubes (Burning Hands, Thunderwave, Cone of Cold). Use `"at": "target_point"` for spells that detonate at a chosen location (Fireball).

---

### `flash`

A bright filled circle at a location that fades out over a fixed duration. Used to mark a hit, an impact, or a magical effect landing on a token.

```json
{"type": "flash", "color": "#FF6600", "at": "target", "duration": 0.25, "size": 1.2}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `color` | hex string | — | Color of the flash |
| `at` | location ref | `"target"` | Location to flash at. Supports `"each_target"`. |
| `duration` | number | `0.3` | Fade-out duration in **seconds** |
| `size` | number | `1.0` | Size multiplier. `1.0` = half a cell diameter. `1.5` gives a noticeably larger flash. |
| `opacity` | number | `1.0` | Starting opacity; fades linearly to 0 over `duration`. An outer glow ring at 30% of this opacity is drawn at 1.5× radius. |

**Notes:**
- The flash draws an inner core at full opacity and an outer glow at 30% opacity and 1.5× radius.
- Short `duration` values (0.2–0.3 s) feel snappy for weapon hits. Longer values (0.4–0.6 s) feel magical or dramatic.
- Always pair with `"at": "each_target"` on AOE spells so each affected creature gets its own visual feedback.

---

### `aura`

A pulsing halo around a token. The glow oscillates via a sine wave and fades out in the final 30% of its duration. Used for buffs, debuffs, and sustained magical effects landing on a creature.

```json
{"type": "aura", "color": "#88CCFF", "at": "caster", "duration": 1.2, "size": 1.6, "pulses": 3}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `color` | hex string | — | Color of the aura glow |
| `at` | location ref | `"caster"` | Token to surround with the aura. Supports `"each_target"`. |
| `duration` | number | `1.0` | Total duration in **seconds** |
| `size` | number | `1.5` | Radius multiplier. `1.0` = half a cell. `1.5` gives a glow slightly larger than the token. |
| `pulses` | number | `2` | Number of full pulse cycles over the duration. Higher = faster flicker. |
| `opacity` | number | `0.6` | Peak opacity of the outer glow ring. The inner ring is drawn at 60% of this value. |

**Notes:**
- The pulse is a sine wave: `sin(progress * pulses * 2π) * 0.5 + 0.5`, so it always starts and ends at 50% brightness.
- The outer glow fades out entirely over the last 30% of `duration`.
- Two concentric circles are drawn: outer at 30% opacity and inner (70% of the outer radius) at 60% opacity.
- Good for: landing buffs (`cure_wounds`, `haste`, `shield_of_faith`), initial buff application, persistent effect activation.

---

### `particles`

A burst of small dots that scatter outward from a point in random directions. Fades out over `duration`.

```json
{"type": "particles", "color": "#FF2200", "at": "target_point", "count": 40, "spread": 30, "duration": 0.6, "speed": 2.0}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `color` | hex string | — | Color of the particles |
| `at` | location ref | `"target_point"` | Origin point for the burst. Supports `"each_target"`. |
| `count` | number | `20` | Number of individual particles in the burst |
| `spread` | number | `20` | Maximum scatter radius in **feet** (converted to cells internally). Controls how far particles travel. |
| `duration` | number | `0.8` | Duration of the burst in **seconds** |
| `speed` | number | `2` | Multiplier on travel distance per frame. Higher values = particles fly out faster relative to `spread`. Negative values cause particles to converge inward (useful for healing effects). |
| `opacity` | number | `1.0` | Starting opacity; fades linearly to 0 over `duration` |

**Notes:**
- Each particle is a small circle (1–3 px radius at zoom 1) placed at a random angle and normalized distance factor each time the spell is cast.
- Use a **negative `speed`** to create an inward-converging effect (e.g. Cure Wounds uses `speed: -1.0` to make green particles flow *toward* the target, suggesting healing energy gathering).
- Combine `spread` (area coverage) with `speed` (velocity feel): high spread + high speed = explosive; low spread + low speed = glittering shimmer.
- `count` 10–15 feels subtle; 25–40 feels explosive.

---

### `beam`

A line drawn between two points that fades out over its duration. Renders a wide glow at 30% opacity underneath a thinner core line for a glowing effect.

```json
{"type": "beam", "color": "#88CCFF", "from": "caster", "to": "target", "duration": 0.4, "width": 3}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `color` | hex string | — | Color of the beam |
| `from` | location ref | `"caster"` | Start point of the beam |
| `to` | location ref or `"direction_endpoint"` | `"target"` | End point of the beam. See `"direction_endpoint"` below. |
| `duration` | number | `0.4` | How long the beam is visible, in **seconds** |
| `width` | number | `3` | Width of the core beam line in pixels at zoom 1. The glow halo is 3× this width. |
| `opacity` | number | `1.0` | Starting opacity; fades to 30% of this value by the end of `duration`. The glow halo fades at 30% of the core opacity. |
| `distance_ft` | number | — | **Required only when `to` is `"direction_endpoint"`.** Length of the beam in feet. |

**`"direction_endpoint"` mode**

When `to` is set to `"direction_endpoint"`, the beam extends from `from` in the direction of `targetPoint` (or the first target) by exactly `distance_ft` feet. This is how Lightning Bolt draws a 100-foot bolt that doesn't stop at the nearest creature:

```json
[
  {
    "type": "beam", "color": "#aaddff",
    "from": "caster_edge", "to": "direction_endpoint",
    "distance_ft": 100, "width": 6, "duration": 0.25, "opacity": 0.95
  },
  {
    "type": "beam", "color": "#ffffff",
    "from": "caster_edge", "to": "direction_endpoint",
    "distance_ft": 100, "width": 2, "duration": 0.25, "opacity": 1.0
  }
]
```

Layering a wide colored beam under a thin white core is the standard technique for a bright lightning bolt.

**Notes:**
- Use `"from": "caster_edge"` instead of `"from": "caster"` so the beam starts at the token's edge rather than the center. This matters most for larger tokens or beams going a long distance.
- The `beam` effect stays fully rendered until `duration` expires — it doesn't travel, it just fades.

---

## Field Quick-Reference

| Field | Effects that use it | Type | Notes |
|---|---|---|---|
| `type` | all | string | Required. One of the six types above. |
| `color` | all | hex string | Required. `"#RRGGBB"` |
| `at` | `flash`, `aura`, `particles`, `expanding_ring` | location ref | Point-effect anchor. Supports `"each_target"`. |
| `from` | `projectile`, `beam` | location ref | Start point |
| `to` | `projectile`, `beam` | location ref | End point. `beam` accepts `"direction_endpoint"`. |
| `duration` | `flash`, `aura`, `particles`, `beam` | seconds | How long the effect is visible |
| `speed` | `projectile`, `expanding_ring`, `particles` | varies | Cells/sec for projectile and ring; distance multiplier for particles |
| `size` | `projectile`, `flash`, `aura` | multiplier | Visual scale relative to a half-cell radius |
| `radius` | `expanding_ring` | feet | Maximum expansion radius |
| `fill` | `expanding_ring` | boolean | Fill interior at 20% opacity |
| `line_width` | `expanding_ring` | pixels | Outline stroke width |
| `width` | `beam` | pixels | Core line width (glow is 3×) |
| `trail` | `projectile` | boolean | Enable trailing particle effect (default: true) |
| `trail_length` | `projectile` | number | Number of trail positions (default: 8) |
| `pulses` | `aura` | number | Sine-wave pulse cycles over duration |
| `count` | `particles` | number | Number of particles |
| `spread` | `particles` | feet | Maximum scatter radius |
| `opacity` | all | number (0–1) | Master opacity |
| `distance_ft` | `beam` | feet | Length for `"direction_endpoint"` beams |

---

## Recipes by Spell Type

### Single-target attack spell
Projectile → Flash on hit.
```json
"animation": [
  [{"type": "projectile", "color": "#FF4400", "from": "caster", "to": "target", "speed": 8, "size": 3}],
  [{"type": "flash", "color": "#FF6600", "at": "target", "duration": 0.25}]
]
```

### Single-target beam/ray spell
Beam appears → Flash on hit.
```json
"animation": [
  [{"type": "beam", "color": "#88CCFF", "from": "caster", "to": "target", "duration": 0.4, "width": 3}],
  [{"type": "flash", "color": "#AADDFF", "at": "target", "duration": 0.3}]
]
```

### Cone / AoE from caster
Expanding ring from caster → Per-target flash.
```json
"animation": [
  [{"type": "expanding_ring", "color": "#FF6600", "at": "caster", "radius": 15, "speed": 8, "fill": true}],
  [{"type": "flash", "color": "#FF4400", "at": "each_target", "duration": 0.3}]
]
```

### Targeted AoE (e.g., Fireball)
Projectile to point → Ring + particles → Per-target flash.
```json
"animation": [
  [{"type": "projectile", "color": "#FF4400", "from": "caster", "to": "target_point", "speed": 12, "size": 3}],
  [
    {"type": "expanding_ring", "color": "#FF6600", "at": "target_point", "radius": 20, "speed": 8, "fill": true},
    {"type": "particles",      "color": "#FF2200", "at": "target_point", "count": 40, "spread": 30, "duration": 0.6}
  ],
  [{"type": "flash", "color": "#FF4400", "at": "each_target", "duration": 0.3}]
]
```

### Buff spell on self or ally
Projectile to target (optional) → Aura on target.
```json
"animation": [
  [{"type": "projectile", "color": "#FFD700", "from": "caster", "to": "target", "speed": 6, "size": 2, "trail": false}],
  [{"type": "aura", "color": "#FFD700", "at": "target", "duration": 1.2, "size": 1.6, "pulses": 3}]
]
```

### Healing spell
Aura on target → Particles converging inward (negative speed).
```json
"animation": [
  [{"type": "aura",      "color": "#44FF88", "at": "target", "duration": 1.0, "size": 1.4, "pulses": 3}],
  [{"type": "particles", "color": "#66FFAA", "at": "target", "count": 15, "spread": 4, "duration": 0.6, "speed": -1.0}]
]
```

### Long directional bolt (Lightning Bolt)
Dual layered beams from caster edge, then per-target effects.
```json
"animation": [
  [
    {"type": "beam", "color": "#aaddff", "from": "caster_edge", "to": "direction_endpoint", "distance_ft": 100, "width": 6, "duration": 0.25, "opacity": 0.95},
    {"type": "beam", "color": "#ffffff", "from": "caster_edge", "to": "direction_endpoint", "distance_ft": 100, "width": 2, "duration": 0.25, "opacity": 1.0}
  ],
  [
    {"type": "flash",     "color": "#aaddff", "at": "each_target", "duration": 0.3},
    {"type": "particles", "color": "#88ccff", "at": "each_target", "count": 12, "spread": 4, "duration": 0.4, "speed": 2.0}
  ]
]
```

---

## Color Conventions

These aren't enforced, but the existing spells follow a consistent palette:

| Damage / Effect type | Suggested color range |
|---|---|
| Fire | `#FF4400` – `#FF6600` (orange-red) |
| Cold / Ice | `#88CCFF` – `#AAEEFF` (light blue) |
| Lightning | `#aaddff` (pale blue), `#ffffff` core overlay |
| Acid | `#AADD00` – `#BBEE22` (yellow-green) |
| Poison | `#66CC22` – `#88DD44` (green) |
| Necrotic | `#550088` – `#9933CC` (deep purple) |
| Radiant | `#FFDD44` – `#FFFF88` (golden yellow) |
| Force | `#9999FF` – `#CC44FF` (blue-violet) |
| Thunder | `#AACCFF` – `#BBDDFF` (desaturated blue) |
| Healing | `#44FF88` – `#66FFAA` (bright green) |
| Buff / Enchantment | `#FFD700` – `#FFEE44` (gold) |
| Charm / Psychic | `#FF88CC` (pink) |
