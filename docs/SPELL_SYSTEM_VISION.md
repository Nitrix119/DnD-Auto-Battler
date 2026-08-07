# Spell System Vision — "Spells as Programs of Blocks"

> **Status: vision / brainstorm, not a plan.** This document records design intent and
> open questions for the spell/combat effect system so they aren't lost. Nothing here is
> committed; it is raw material for later design work. Where it describes the *current*
> system, that is factual; where it describes the *target*, that is aspiration.

---

## 1. The premise

D&D 5e's combat is enormous, deep, and irregular. Almost every spell bends or breaks the
"common" pattern in some way, and the long tail of interactions (concentration, riders,
conditional effects, granted actions, spells that cast other spells) is effectively
unbounded. Hand-coding each spell does not scale, and neither does a rules engine that
special-cases spells by name.

The bet this project makes: **model combat as a small set of composable, data-defined
effects executed by a generic pipeline, and express the diversity of D&D as
*combinations* of those effects rather than as bespoke code.** Adding content should be
authoring data; only genuinely novel mechanics should require new engine primitives.

The endgame: a system built to absorb the vastness of D&D combat, where adding a spell is
writing a JSON program, and the rare spell that needs a truly new capability is handled by
adding **one new, well-specified block** to the vocabulary — not by carving a special case
into the resolver.

---

## 2. Where we are today (the honest baseline)

The engine already leans hard in this direction, which is why it works as well as it does:

- A spell is a list of **pipeline steps** (`pipeline_effects`) run in order by
  `EffectPipeline` over a shared, ephemeral `context`. Steps read/write context so later
  steps can branch on earlier results (`context.hit`, `context.damage_dealt`,
  `context.save_success`). Today's step types: `attack_roll`, `saving_throw`, `damage`,
  `healing`, `add_entity_effect`, `apply_condition`, `add_modifier`, `grant_temporary_hp`.
- Weapon attacks compile into the *same* steps, so there is one resolution path.
- Longer-lived behaviour lives as **named entity effects** — separate JSON files under
  `rules/entity_effects/` — that subscribe to `EventBus` events and run **rule effects**
  from a second vocabulary (`BUILTIN_EFFECTS` in `src/rules/effects.py`:
  `GrantAction`, `AddModifier`, `ApplyCondition`, `ModifyDamage`, `GrantTemporaryHP`,
  `GrantAdvantage`, …).
- Expressions in either place run in a sandbox (`src/rules/expressions.py`).

**The crux of the dissatisfaction:** there are effectively **two effect vocabularies**
bridged by synthetic events — the pipeline's step types *and* the rule engine's
`BUILTIN_EFFECTS`. A spell's identity is split across a spell JSON *and* one or more
separate entity-effect JSONs. A single spell is not defined in one place.

### Case study — Vampiric Touch (the motivating abomination)

Vampiric Touch is the poster child. It:

1. makes a melee spell attack,
2. deals necrotic damage,
3. heals the caster for **half the damage this attack dealt**,
4. grants a **repeatable action** to do (1–3) again on later turns,
5. all **only while concentration holds**.

Today (see `examples/spells/vampiric_touch.json` + `rules/entity_effects/vampiric_touch.json`):
the attack/damage/heal live in the spell's `pipeline_effects`, but the "grant a repeatable
action, tied to concentration" part must be pushed out into a **separate entity-effect
file**, whose `on_apply` then `GrantAction`s a fresh attack. The spell's behaviour is
smeared across two files and two vocabularies, and the granted action has to re-derive
context (caster's spell attack bonus, damage) by hand. Armor of Agathys has the same shape
(a reactive retaliation rider that must live as a separate effect).

This works — but it is exactly the split the vision wants to erase.

---

## 3. The target: one block language, one definition per spell

**Rename and reframe `effects` as `blocks`** (name TBD — "block", "op", "instruction")
in a *quasi–block-based programming language for spells*. A spell (or any action) is a
**program**: an ordered, nestable list of blocks over a shared context. The **entire**
identity of a spell — its damage, saves, healing, the buffs/debuffs it applies, the
actions it grants, its concentration linkage, its retaliation riders — is expressed in
**one definition**, using blocks, with no obligatory second file.

Guiding properties:

- **One spell, one program.** Granted effects, granted actions, and reactive riders are
  just blocks (or sub-programs) inside the spell, not separate hand-authored entity
  effects. The engine may still *instantiate* a persistent effect under the hood, but the
  author writes it once, inline.
- **Uniform vocabulary.** Collapse the pipeline-step vocabulary and the rule-engine
  `BUILTIN_EFFECTS` vocabulary into **one block catalogue**. "Deal damage" is the same
  block whether it fires now or from a triggered rider later.
- **Blocks are values with a contract.** Each block declares what it reads from context,
  what it writes, what it targets, and when it runs. Composition is explicit.
- **Triggers are blocks too.** "Do X when Y happens" (retaliation, concentration ticks,
  once-per-turn riders) is a block that registers a sub-program against an event —
  authored inline, not as a separate file.

### A sketch (illustrative only — not a proposed schema)

```
Vampiric Touch:
  concentration: true
  program:
    - attack_roll:        { bonus: caster.spell_attack_bonus }
    - damage:             { formula: 3d6, type: necrotic, when: hit }
    - heal:               { target: caster, amount: context.damage_dealt // 2 }
    - grant_repeat_action: # a block that re-runs this same program on later turns,
        while: concentration # bound to the spell's concentration, defined right here
```

The point is not this syntax — it is that step 4 ("grant a repeatable action bound to
concentration") is a **first-class block in the same file**, capturing the parent
program's context, instead of a separate entity-effect JSON.

---

## 4. The block catalogue (a taxonomy to define precisely)

The system's rigor comes from a **strict, well-defined set of block types** with exact
contracts. A first cut at the categories (to be pinned down, named, and schema'd):

- **Rolls / gates:** `attack_roll`, `saving_throw`, ability checks; write hit/save results
  and advantage state to context.
- **Damage & healing:** typed damage (with `roll_once`, crit doubling, save-based
  reduction), healing, temporary HP.
- **State on a creature:** apply/remove **conditions**; add/remove **stat modifiers**
  (buffs/debuffs, AC, saves); grant/revoke **resources** and **actions**.
- **Persistence & lifetime:** attach a **duration-bound effect** (rounds/minutes/
  concentration); tick and expire it; **revoke** it. Concentration is a lifetime binding,
  not a bolt-on.
- **Control flow:** conditionals (`when`), branching on context, iteration over targets,
  sub-programs.
- **Triggers / reactions:** register a sub-program against an event (on-hit retaliation,
  start-of-turn, on-damage), scoped to the effect's lifetime.
- **Targeting:** self / target / area / derived sets; a block declares whom it acts on.
- **Meta / higher-order:** the rare, powerful ones — **cast another spell as an effect**
  (Wish, Contingency, glyphs), **scale by slot level** (upcasting as a block modifier),
  copy/counter another action. These are where the "add one new block" escape hatch earns
  its keep.

Each block gets a spec: inputs, defaults, the context keys it reads and writes, its
targeting, its timing/event, and its failure behaviour.

---

## 5. Schema + linter (the necessary discipline)

If spells become programs, they need a **language spec**: a strict, machine-readable
**schema** for every block — required/optional fields, value domains, the context
contract — plus a **linter** that validates a spell definition before it ever runs.

Why this is load-bearing, not optional:

- It is the **authoring contract**. A human or an LLM (the future "add a new spell" skill)
  writes against the schema and gets precise, local errors instead of a silent no-op or a
  runtime crash three steps later.
- It kills the current class of **silent failures**: an unknown block, a typo'd field, a
  block whose `when` references a context key that step can't have produced, a save-result
  on a step with no save. (This is also the clean home for the deferred **E6** debt — a
  field/context schema is exactly what lets us tell "wrong event" from "author typo".)
- It makes the block catalogue **self-documenting** — the schema *is* the reference the
  guides are generated from.

The extensibility principle falls out of this: **to support a spell whose signature
mechanic isn't expressible, you write one new block, give it a schema entry, and the
linter + authors get it for free.** Wish casting another spell becomes a `cast_spell`
block, not a special case in the resolver.

---

## 6. Hard cases to design *against* (where it will try to break)

Per this project's ethos, the design is judged by how it handles the ugly cases, not the
clean ones. A non-exhaustive list to keep honest:

- **Context capture across time.** A granted/triggered sub-program (Vampiric Touch's
  repeat, Armor of Agathys' retaliation) runs *later* — which context does it see: the
  original cast's, or a fresh one? Damage riders that reference "this attack's damage" need
  a well-defined, per-invocation context, not a stale snapshot.
- **Concentration as a first-class lifetime.** Starting a new concentration spell must drop
  the old one *and its entire block subtree* deterministically; a failed concentration save
  must revoke exactly what the spell granted (actions, modifiers, effects) and no more.
- **Ordering and re-entrancy.** Blocks that emit events that trigger other blocks (a damage
  block that kills a creature that has an on-death rider) need defined ordering and loop/
  re-entrancy guards. "Roll once, apply to all" (AoE) must stay correct under composition.
- **Revocation and cleanup.** Every "grant" needs a matching "revoke" with clear ownership,
  so effects don't leak or double-remove (today's pipeline already tiptoes around removing
  the old concentration effect before applying the new one).
- **Targeting edge cases.** Self-damage exclusion, dead/invalid targets mid-program,
  empty AoE, friendly-fire flags — decided per block, not ad hoc.
- **Stacking & idempotence.** Non-stacking temp HP, non-stacking same-named buffs, repeated
  application of the same rider — the block semantics must say what "apply again" means.
- **Upcasting/scaling.** Should be a *modifier over blocks* (more dice, more targets,
  longer duration), not copy-pasted higher-level spell files.
- **Determinism.** The whole program must be reproducible under a seeded RNG
  (`dice.seed_rng`) — including triggered sub-programs that fire on later turns.

---

## 7. Migration sensibilities (for whenever this is tackled)

Not a plan — just constraints worth honouring when the time comes:

- **Keep the unified attack/spell pipeline.** It is the strongest existing property; the
  block model should generalise it, not replace it.
- **Preserve the event bus** as the substrate for triggers/reactions; "trigger blocks" are
  a friendlier authoring face over the same mechanism.
- **Fold `BUILTIN_EFFECTS` and pipeline steps into one catalogue** rather than maintaining
  two — that duplication is the smell driving this whole vision.
- **Schema-first, then linter, then migrate content**, so the existing 22 spells become the
  first conformance corpus and the regression net.
- **Grow the block set empirically:** implement the blocks the current spells need, then add
  new blocks only when a real spell demands one (the Wish test).

---

## 8. Open questions

- What is the right **name** for a block, and for the whole file (still "spell"? "action
  program"?).
- How much **control flow** belongs in data before it stops being data and becomes a
  programming language we have to debug? Where's the line between "expressive blocks" and
  "reinventing Python badly in JSON"?
- Do blocks **nest** (sub-programs as block arguments) or stay flat with references?
- How are **context contracts** expressed and checked — inferred from block specs, or
  declared per block?
- Where do **conditions** (the 17 status conditions) live — as blocks, as data the blocks
  read, or both?
- Is there a place for a **visual/block editor** later, given the "block-based programming"
  framing?

---

_See also: [CODEBASE_REVIEW.md](CODEBASE_REVIEW.md) §3 (why the current spell system is
sound but has two effect vocabularies), and the current authoring guides under
`examples/spells/` (`SPELL_DEFINITION_GUIDE.md`, `ANIMATION_GUIDE.md`)._
