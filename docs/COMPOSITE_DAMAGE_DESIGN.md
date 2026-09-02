# Composite Damage & Per-Type Modifiers — design note

> **Status: design note / open problem, not a plan.** Captures a known correctness gap
> and a sketched direction to refine later. The gap **predates** the block-system rework
> (it lives in the damage-modifier rules themselves, not the migration), so it is recorded
> here rather than fixed inline. See also [SPELL_SYSTEM_PHASE3_PLAN.md](SPELL_SYSTEM_PHASE3_PLAN.md)
> §6 ("Multi-component damage / per-entry resistance") and the recurring
> `damage-typing-per-entry-resistance` note.

---

## 1. The gap — resistance/immunity/vulnerability applies to the wrong scope

The three damage-modifier rules (`rules/global/damage_{resistance,immunity,vulnerability}_rule.json`)
currently gate on the **first** damage component and then scale the **whole** incoming
damage. In effect:

- **Condition:** `event.damage_list[0].damage_type in event.defender.stat_block.damage_resistances`
- **Effect:** `ModifyDamage(multiplier=…)` over the entire `damage_list`.

That is correct for a single-type hit, but **wrong for composite damage** — one attack that
deals more than one type at once (a flame-tongue longsword: `1d10 slashing + 1d6 fire`; a
spell with mixed typing; an on-hit rider adding a different type).

**5e RAW:** a mixed-type hit is still **one instance of damage / one hit**, but each
resistance / immunity / vulnerability applies **only to its own type**. A creature immune to
(nonmagical) slashing and vulnerable to fire, hit for `1d10 slashing + 1d6 fire`, takes:

```
(1d10 × 0) slashing  +  (1d6 × 2) fire   =  just the doubled fire
```

Today's rule would instead read the first component's type, decide "resisted / immune /
vulnerable", and apply that one multiplier to the sum — both over- and under-counting
depending on component order.

Two coupled shortcomings:

1. **Scope:** modifiers are applied to the whole packet, not per component/type.
2. **First-component gating:** the outcome depends on `damage_list[0]` ordering, which is
   incidental.

This must stay honest with the project ethos (model the rules or decline loudly) — right
now it silently mis-models composite hits.

---

## 2. Sketched direction — a first-class "damage packet" wrapping typed components

Introduce a class for a **full instance of damage** (working name: `DamagePacket` /
`DamageBundle`) that wraps an ordered list of individual typed components (today's
`Damage`). One packet == one hit == one instance of taking damage. Benefits:

- **Correct per-type modifiers.** Applying the packet to a defender iterates its components
  and applies each defender modifier **only to matching-type components** — immunity zeroes
  its type, resistance halves its type, vulnerability doubles its type, independently. The
  ambiguous `damage_list[0]` gate disappears.
- **One hit stays one hit.** Per-hit reactive triggers (Fire Shield, Armor of Agathys'
  retaliation, "when you take damage" riders) fire **once** per packet, not once per
  component — the packet is the unit of "a hit landed".
- **Riders append, they don't restart.** Colossus Slayer (and similar on-hit bonus dice)
  **append a component** (`1d8` of the weapon's type) to the *same* packet, so it is still
  one hit for per-hit triggers, and the bonus die is itself subject to the defender's
  per-type modifiers.
- **Primary damage type has a natural home.** The packet can expose `primary_damage_type`
  (e.g. its first/largest component), which is what a weapon attack yields for a rider like
  Colossus to inherit — replacing today's `Action.primary_damage_type` scan of
  `pipeline_effects`/`damage`.
- **Modifiers at roll time.** If the packet carries (or is handed) the defender's modifier
  set, it can resolve amounts at **dice-rolling time** — roll each component, apply its
  type's multiplier — rather than rolling then re-scaling a flat total after the fact. This
  also simplifies the resistance rules from an event-mutating `ModifyDamage` into a property
  of applying the packet.

### Where it touches

- `src/models/damage.py` — the new packet type alongside `Damage`.
- `src/combat/damage_processor.py` — apply a packet, iterating components × defender
  modifiers; emit the per-hit events once per packet.
- The block `damage` handler and `DamageIncomingData` — carry a packet, not a bare
  `damage_list`; the resistance/immunity/vulnerability rules become per-type application
  (possibly folding away as explicit rules entirely once the packet applies its own
  modifiers).
- Colossus Slayer's rider and `Action.primary_damage_type` — append to / read from the
  packet.

### Open questions

- Do the resistance/immunity/vulnerability **rules** survive as event-modifiers at all, or
  does per-type modifier application move **into** packet-apply (so those three JSON rules
  retire)? The latter is cleaner but changes where the behaviour lives.
- **Magical/nonmagical (and source) qualifiers** on resistances ("resistance to nonmagical
  slashing") — the packet/components likely need a `magical` / source flag to model these,
  which the current type-only lists don't carry.
- **Halving/rounding order** with multiple modifiers on one type (5e: a type is never
  resisted-and-vulnerable to compound; resistance and vulnerability on the same type cancel)
  — decide the per-type resolution rule explicitly.
- Interaction with **"roll once, apply to all"** AoE and with save-based halving (half on a
  successful save is a packet-level scale, distinct from per-type modifiers).

---

_Recorded 2026-09-03 while migrating the damage-modifier rules to native block programs
(Phase 3 §5d) — the migration preserved the existing (flawed) behaviour exactly; this note
is the follow-up to fix it properly._
