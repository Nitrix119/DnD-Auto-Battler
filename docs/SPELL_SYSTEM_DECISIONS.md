# Spell System — Open Decisions & Questions

> **Purpose.** Every question, decision point, and place where the design in
> [SPELL_SYSTEM_DESIGN.md](SPELL_SYSTEM_DESIGN.md) needs *your* input, collated so you can answer
> each in one pass. Where I have a view I've marked a **Recommendation**; where I don't, the options
> are laid out neutrally.
>
> **How to respond:** write under each **Your answer:** line (the `> _…_` block). "Agree" / "recommendation
> is fine" is a complete answer — I'll only follow up where you push back or add nuance. Answer as many or
> as few as you like; the ones gating the first work are flagged **⛳ gates stage 1**.

---

## A. Scope & commitment

### A1. Is this greenlit at all, and how far? ⛳
The design doc is explicitly pre-commitment. Before anything else I need to know the ceiling.

- **(a)** Just the docs — capture the thinking, build nothing yet.
- **(b)** Stage 1 only (schema + linter for today's `effects` shape, no behaviour change). *Recommended
  as the first concrete step — highest leverage, no rewrite, unblocks the "new spell" skill and
  retires E6.*
- **(c)** Stages 1–3 (schema, upcasting, split-targeting) — pure additions on today's architecture.
- **(d)** Full arc through single-file spells (stages 1–6+), i.e. the actual unification.

**Recommendation:** (b) now, with (c) as the likely follow-on; treat 4–7 as a separate decision once
1–3 land.

**Your answer:**
> (a). I'm trying to create a good plan that addresses problems before we start writing.

### A2. Should the one live bug be fixed independently, now? ⛳
§6.4 flags a real defect, not just a design smell: `inject_pipeline_damage_step`
([effects.py:286](../src/rules/effects.py#L286)) appends to `action.pipeline_effects` mid-iteration
**and mutates the shared `SpellAction`**, so a second cast can double-inject. This exists today,
independent of any redesign.

- **(a)** Fix it now as a standalone bugfix (failing test first, per CLAUDE.md §4).
- **(b)** Leave it; fold into the stage-4 unification that removes list-surgery entirely.

**Recommendation:** (a) — it's a latent correctness bug with a real repro; don't wait on the rewrite.

**Your answer:**
> (a). Best to just fix it now, if it's a clear correctness problem. No reason to leave something like this that might confuse future work.

---

## B. Naming & syntax

*(None of these gate stage 1 — the linter can validate today's `effects`/step vocabulary under its
current names. They matter once we introduce the unified catalogue. Answer now if you have a
preference; otherwise "defer" is fine.)*

### B2. What do we call a single instruction?
The vision floated `block` / `op` / `instruction`. The doc used `block` illustratively.

- `block` (fits the "block-based programming" and future visual-editor framing)
- `op` / `instruction` (more precise, less friendly)

**Recommendation:** `block`.

**Your answer:**
> Block is the most clear given the breadth of what a block can do.

### B3. What do we call the array, and the file?
Today: `effects` array in a file we call a "spell." Target doc used `program`.

- Keep `effects`; keep "spell."
- Rename the array to `program`; keep "spell" as the file/domain word.
- Rename both (e.g. "action program").

**Recommendation:** rename the array to `program` eventually, keep "spell" as the user-facing word
(weapons already compile into the same steps, but "spell" is what content authors think in).

**Your answer:**
> 'Program' internally makes sense, what we call it user-facing is easy to change for clarity.

### B4. Keep the legacy `effects` shape loadable during migration?
§6.10 proposes an adapter that reads old step dicts as blocks so the 22 spells migrate incrementally,
not in a big bang.

**Recommendation:** yes — commit to backwards-compat via an adapter; never require a flag-day rewrite
of all content.

**Your answer:**
> Yes - it should be extrmemely minimal work to maintain backwards-compatability at least until migration is complete. There are many simple approaches that would work, such as simply prefixing old spells with 'old_' and using that as the condition for using the old resolution pipeline. I don't want to keep the old system forever, but keeping it during the rework is clean.

---

## C. Language-design boundaries

### C1. Ratify the "data, not a programming language" hard line? ⛳ (informs the linter)
§6.11's stance: **no author-defined variables, no loops except bounded iterators over target sets, no
author-defined functions.** Expressions stay side-effect-free and sandboxed. Anything needing real
computation becomes a registered Python block, not author-written control flow.

**Recommendation:** adopt this as a stated constraint now — it bounds the linter and every future
block. If you disagree, this is the single most important thing to say so on.

**Your answer:**
> Yes, this makes sense to me. User-defined varaibles, loops, and similar seem like they would only casue trouble. Things that do genuinely need some caching (like referencing damage done) are cleanly handled by spell context sessions, and bounded iterators are simple enough.

### C2. Context contract — declared per block, or inferred from the handler?
The linter's context-flow check (a `when` may only read keys some earlier block writes — the thing
that retires E6) needs to know each block's `reads`/`writes`. §5.5 assumes each block *declares* them;
they could instead be inferred from the handler body.

- **Declare** (explicit `reads=[…], writes=[…]` per registration — more boilerplate, trivially
  checkable, doubles as docs).
- **Infer** (parse the handler — less boilerplate, more magic, fragile).

**Recommendation:** declare. The boilerplate is the schema and the generated docs; inference buys
little and costs clarity.

**Your answer:**
> Declare. I can't say I fully understand this one, but something you'd describe as 'magic' sounds like a bad idea. Boilerplating is clean.

### C3. Do blocks nest only via `then`, or also take sub-programs as named arguments?
E.g. a `damage` block with an `on_kill:` argument **vs.** a separate `on_kill` trigger block. The doc
leans toward triggers-only (§6.4) to keep all re-entrancy in one mechanism.

**Recommendation:** triggers/`then` only, no sub-programs-as-arguments — one nesting mechanism, one
place to reason about ordering and re-entrancy. (Revisit only if a real spell forces it.)

**Your answer:**
> Trigger blocks seem clean for now, especialyl in cases like this. But it's hard to answer this one concretely. There may well be at least some conditions where nesting is necessary, but until it's proven to be necessary let's not do it. Implementation should be simple enough if we have to allow the program resolution pipeline to self-reference in order to read a subprogram.

### C4. Where do the 17 status conditions live?
As blocks, as data the blocks read, or both? Making them a **shared library** is natural but
reintroduces multi-file authoring for exactly the reusable case (§3 C2, §8).

- Conditions stay as reusable named effects (a shared library the `apply_condition` block references).
- Conditions become inline blocks (no shared file, but 17 definitions duplicated wherever used).
- Both (library for the canonical 17; inline blocks for one-off spell-specific states).

**Recommendation:** keep the canonical conditions as a shared library referenced by an
`apply_condition` block; allow inline one-off states. Multi-file is acceptable *for genuinely
reusable* effects — that's different from a per-spell rider being forced into a second file.

**Your answer:**
> Both. There should be a library for referencing extremely common content, such as these conditions which a massive number of spells apply. But there should be functional equivalency between defining the condition inline and referencing it, and inline is obviously the intent for one-off states.

---

## D. Architecture decisions

### D1. Ratify lifetime scopes + grant handles as the concentration/revocation model?
§6.3 / §6.5 replace today's `source_effect`/`effect_name` string-tag conventions with a lifetime-scope
object that owns revoke handles; teardown walks handles in reverse. Concentration becomes one kind of
lifetime.

**Recommendation:** adopt for stage 5. Flagging because it's the biggest conceptual shift and touches
`Entity`.

**Your answer:**
> Recommendation is perfect. The existing concentration handling is a terrible hack - limited changes to Entity are okay for such a sensible change as improving the handling of these tags.

### D2. Fold AoE fan-out into the general targeting/iterator mechanism?
Today the per-defender loop lives implicitly in `SpellResolver.resolve`. §6.6 makes it one iterator
block among several (alongside split-multi-target). Alternative: keep AoE special-cased and only add
split-targeting beside it.

**Recommendation:** unify (stage 3) — "roll once, apply to all" and "roll per dart" under one
iterator is cleaner and kills the Magic Missile fake.

**Your answer:**
> Recommendation is perfect. AOE is too common to be doing anything weird when it comes to multi-target. Different targeting types should hopefully be handled as simple different iterator blocks as needed.

### D3. Determinism: is "subscription order, then initiative" an acceptable trigger-ordering rule?
§6.8 needs a stable ordering for same-turn triggers so seeded replays don't diverge. Any documented,
deterministic rule works; I proposed subscription order then entity initiative.

**Recommendation:** accept that rule unless you know a 5e-correctness reason to prefer another (e.g.
strict initiative order for reactions).

**Your answer:**
> I can't think of any reasons right now why certain triggers must happen before others in regards to 5e correctness. A compromise could be to give an optional 'priority' field to deferred triggers like this, which may never be used but is dead easy to add and solves cases for same-turn triggers if they truly do need to fire first/last.

### D4. Upcasting shape — a context name **and** a `scaling` modifier?
§6.7: expose `slot_level` as a context value *and* give scalable blocks an explicit `scaling` field
(`{ "per_slot_above": 3, "add_dice": "1d6" }`), rather than making raw dice formulas into
expressions.

**Recommendation:** yes to both — keep dice formulas as dice strings; scaling is a declared modifier.

**Your answer:**
> Recommendation is perfect. If it comes to it, new blocks to define weird scaling stuff should be easy within a good implementation of this framework. The core is that spell level is in the context to allow this.

### D5. When do we resolve the process-global registry / per-session isolation (E12)?
Lifetime scopes and per-battle trigger queues make the shared-registry concern more urgent. The doc
suggests handling it alongside stage 5.

- Alongside stage 5 (when it starts to bite).
- Sooner, as its own hardening task (it's already listed as open in CODEBASE_REVIEW E12).
- Not now.

**Recommendation:** alongside stage 5, unless concurrent battles become a near-term product need.

**Your answer:**
> Recommendation is perfect.

---

## E. Sequencing & process

### E1. Accept the staged roadmap order (§7)? ⛳
Schema/linter → upcasting → split-targeting → unify damage/heal twins → lifetime scopes → inline
triggers → meta/`cast_spell`. Each stage is independently valuable; none requires the next.

**Recommendation:** accept as the default order; 1–3 are safe additions, 4–6 are the real unification,
7 is the proof. Re-plan after 3.

**Your answer:**
> Recommendation is perfect - returning to the plan when we've got some code in place to work from is a great idea.

### E2. Confirm the conformance-corpus migration method?
§6.2 / §6.10: before deleting any old code path, dual-run old and new interpreters over the same
seeded inputs across all 22 spells and assert identical `PipelineResult`s.

**Recommendation:** yes — this is the regression net that makes the unification safe.

**Your answer:**
> Yes. As mentioned before, it's a reasonably simple thing to split interpreting in some really simple way (even just file names - probably <10 lines), and avoid breaking anything until we're ready.

### E3. Should stage 1 also generate the authoring guide from the schema?
The doc proposes the schema become the single source for `SPELL_DEFINITION_GUIDE.md`'s step tables
(ending code/doc drift). That's extra scope on stage 1.

- Yes — generate the guide tables from the schema as part of stage 1.
- No — keep the guide hand-maintained for now; just validate.

**Recommendation:** generate it — drift between guide and code has already bitten (the guide is
currently a second source of truth). But it's optional to stage 1's core value.

**Your answer:**
> Yes. It's great for keeping a source of truth, guiding future agents, and challenging our own work if definition doesn't make sense.

---

## F. Longer-horizon / non-blocking

### F1. Is a visual/block editor a real goal, or just a nice framing?
Affects how much the schema (§5.5) should be editor-oriented (stable IDs, positions) vs. purely a
validation contract.

**Recommendation:** treat as aspirational only; build the schema as a validation/docs contract first,
don't pay editor costs speculatively.

**Your answer:**
> Absolutely not - recommendation is perfect. It is unlikely that many spells will be defined by a human, I'm just trying to get a good framework for the sheer volume of weird things 5e spells can do.

### F2. Anything you want captured that isn't here?
Free space for constraints, priorities, or spells you specifically want expressible (a good forcing
function — name the spell that must work and it'll shape the block set).

**Your answer:**
> Nothing specifically. A lot of the really, really wacky nonsense, like 'Simulacra', can probably be neatly handled by offloading their absurd effects (like entity creation) to new blocks. This is a good one to just think about, though, along with other summons. Block definition will need a lot of things, though is endlessly safer than handing any real python coding to spell definition.

---

_Source: [SPELL_SYSTEM_DESIGN.md](SPELL_SYSTEM_DESIGN.md) (§3 target model, §6 challenges, §7 roadmap,
§8 open questions) and [SPELL_SYSTEM_VISION.md](SPELL_SYSTEM_VISION.md) §8. Once answered, I'll fold
the decisions back into the design doc and, if greenlit, draft the stage-1 plan._
