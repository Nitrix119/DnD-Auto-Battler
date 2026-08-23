# Summoning & Entity Lifecycle — Problems & Open Decisions

> **Purpose.** [SPELL_SYSTEM_DESIGN.md](SPELL_SYSTEM_DESIGN.md) §6.12 flags summoning / entity
> creation as the one block family that reaches *outside* the caster/defender pair and stresses the
> roster, initiative, lifetime, and determinism at once — the sharpest test of "add one block absorbs
> all of 5e." This document explains each problem in enough detail to decide against, and asks the
> questions whose answers will shape the `entity_lifecycle` block family before stage 4 freezes the
> block model.
>
> **How to respond:** write under each **Your answer:** line. "Recommendation is fine" is complete.
> I've referenced how a CRPG like **Baldur's Gate 3** tends to handle each point where it might jog an
> intuition — treat those as prompts, not constraints; this is a turn-based 5e sim, not BG3, so we can
> diverge freely.
>
> **Grounding (current code facts this doc relies on):**
> - Entity identity is a random `uuid.uuid4()` ([entity.py:27](../src/models/entity.py#L27)) — **not**
>   seed-stable.
> - `CombatSystem.add_combatant` exists and appends to `combatants` + `InitiativeTracker`, which keeps
>   a **sorted list indexed by a positional `current_turn_index`** ([initiative.py](../src/combat/initiative.py)).
> - A `team` faction field exists ([entity.py:33](../src/models/entity.py#L33); `None` = hostile to
>   all) plus `is_player_controlled`.
> - **There is no autonomous AI turn loop yet** (CODEBASE_REVIEW §2) — every action is driven
>   externally.

---

## A. Scope — what must be expressible

### A1. Which summon archetypes must the model cover (and in what priority)?
"Summoning" is really several mechanics with different shapes. The block family only has to serve the
ones we care about — naming them bounds the design.

- **Fixed statblock** — one predefined creature (a *Summon Elemental*'s "Elemental Spirit", *Spiritual
  Weapon*, *Flaming Sphere*). Simplest: reference a creature JSON, place it, bind its lifetime.
- **Choice from a list** — *Conjure Animals* ("one CR 2, or two CR 1, or four CR ¼…"), *Find Familiar*
  (pick a form). Needs an author-declared menu + a chooser.
- **Copy of an existing creature** — *Simulacrum* (a copy of a real creature at half HP, its own spell
  list, can't regain resources), *Animate Dead* (a corpse → zombie/skeleton), *Clone*. Needs to read
  another entity/statblock and derive from it.
- **Horde / many at once** — *Animate Objects* (up to 10 objects), *Conjure Animals* (up to 8). Needs
  the batch to share one lifetime and (maybe) act as a group.

**Recommendation:** design for **fixed statblock first** (it exercises roster/initiative/lifetime
without the copy/menu complexity), make **choice-from-a-list** and **horde** fall out of the targeting
iterator (§6.6) + a creature-menu field, and treat **copy-of-a-creature** (Simulacrum) as the explicit
hard case handled last (see F1). Confirm the priority, and flag any archetype that must work early.

**Your answer:**
> Recommendation is perfect. Easy, straight-forward cases first (spawning in a new entity from a normal statblock), and then multi-summoning does seem to naturally come along with multi-targeting support as mentioned. Simulacrum is complicated, niche, and extremely unique, so it's completely reasonable to keep copy-based summoning out of scope for now.

### A2. Do summoned creatures act autonomously, or are they externally driven like everything else?
There is no AI turn loop today — the frontend/caller drives every action. A summon that "takes its
turn and attacks" has nothing to move it unless we say what does. (In BG3 the player directly controls
their summons; the game doesn't auto-play them.)

- **(a)** Summons are just combatants in initiative; whatever drives *other* turns (the future AI loop,
  or the external caller) drives them too. No special autonomy in the engine now.
- **(b)** Summons get a lightweight built-in behaviour (e.g. "attack nearest enemy") so they act even
  before the AI loop exists.
- **(c)** Summons are controlled by the summoner's controller (player commands them), never
  independent.

**Recommendation:** **(a)** — model summons as ordinary combatants with a `team` and an initiative
slot; *who chooses their action* is the same open question as for monsters and is out of scope for the
block family. Don't build a bespoke summon-AI now. Revisit once the AI loop exists.

**Your answer:**
> (a). Recommendation is good - just treat them like another member of the respective team. For context, it's unlikely that a team will ever have more than one single controller, be it AI or human. An AI controller might do something like spawn agents to get orders for each combattant, but it should always come from a single instance of a `Controller` object or similar.

---

## B. Identity & determinism

### B1. Adopt seed-stable entity IDs so summons don't break reproducibility?
CLAUDE.md §1 promises a battle replays exactly under `dice.seed_rng`. But entity IDs are
`uuid.uuid4()` — random every run. A *pre-placed* creature getting a random ID is harmless (it's the
same object across the run), but a creature **created mid-battle** gets a fresh random ID each run, so
any log, ordering, or targeting that touches that ID diverges between two seeded replays. Summoning is
the first feature that makes the random-UUID choice actually bite.

- **(a)** Give summoned entities **deterministic IDs** derived from the seed + summoner id + a
  per-battle counter (e.g. `"<summoner>::summon::3"`). Pre-placed creatures can keep UUIDs or move to
  stable ids too.
- **(b)** Route all ID generation through the seeded RNG so even UUIDs are reproducible.
- **(c)** Accept non-determinism for summoned entities (drop the replay guarantee for battles with
  summons).

**Recommendation:** **(a)** — a small, contained change (a deterministic id factory for created
entities) that preserves the replay guarantee, which is a stated core principle. Reject (c).

**Your answer:**
> Recommendation is perfect.

### B2. Where does a summon's statblock come from?
The `summon` block needs a source for the creature it creates. Options, not mutually exclusive:

- **By name from a creature registry** — `{ "summon": "elemental_spirit" }` looks up a creature JSON
  (mirrors how spells are registered). Clean for fixed/menu summons.
- **Inline** — the statblock is embedded in the spell file. Keeps one-file authoring but bloats spells
  and duplicates common creatures.
- **Derived from a live entity** — Simulacrum/Animate Dead read an existing `Entity`/`StatBlock` and
  transform it (half HP, swap type). The hard case (F1).

**Recommendation:** **by name from a creature registry** as the primary path (consistent with the
"shared library for reusable content" decision, C4 in the spell doc), inline allowed for one-offs
(functional equivalence, same as conditions), and derived-from-entity as an explicit F1 mechanism.

**Your answer:**
> Recommendation is perfect, and consistent with established DnD 5e rulebook and gameplay precident. Creatures are almost always referenced by name and have their statblocks defined separately for cleanliness. This is also way more sensible, since it means that these same creatures can be used as starting combattants, rather than locked in spell definitions and bloating. This is another perfect use of the shahred library concept. But of course there are some cases where they need to be defined bespoke, so the library vs inline equivalence is important.

---

## C. Battlefield integration

### C1. Where does a summon land in initiative — and how do we insert without corrupting the turn pointer?
`InitiativeTracker` holds a **sorted list** and tracks the current turn by **positional index**
(`current_turn_index`). Inserting a combatant mid-round re-sorts the list, which can shift every index
after the insertion point — so the "current turn" pointer can silently move to the wrong creature,
skip, or repeat a turn. Any mid-combat insert must update that pointer deliberately. Separately, 5e
itself has to decide *when* the summon acts.

Initiative-placement options (5e is inconsistent across summons; pick a default):
- **Own initiative roll** — the summon rolls and slots in (may act this round or next depending on
  position). Most "monster" summons.
- **On the summoner's initiative** — the summon acts immediately after/with the caster (BG3 tends to
  give summons their own initiative slot, but "acts on your turn" is common in tabletop for things
  like *Spiritual Weapon*, which you move+attack with using your own action/bonus action).
- **Next round only** — never acts the round it's summoned.

**Recommendation:** default to **own initiative roll** for creature-summons (insert *after* the
current turn index so it can't hijack the in-progress turn; make `InitiativeTracker` insertion
pointer-safe as a prerequisite), and treat "acts on the caster's turn" cases (*Spiritual Weapon*,
*Flaming Sphere*) as **positioned effects the caster operates**, not independent combatants — see F2.
Tell me if you'd rather all summons act on the summoner's turn (simpler, less "real").

**Your answer:**
> Recommendation looks good. To elaborate from established D&D rules, summons generally roll thier own iniative (in 5e, which we are using. 2024 edition actually uses the suggestion of summons acting on the summoner's turn, and we are not using this ruleset). There are some wacky cases, however, such as 'Conjure Woodland Creatures' being able to summon numerous creatures, which have separate turns, but are directly stated to roll a single shared iniative roll for all of them. But this is an easy feature to allow for with a small extra field on the summoning block, so just worry about the simplest case (one summoned creature - roll own iniative) for now. In the case of a summon's iniative roll tying with an existing combattant, the rules are fuzzy. Technically the rule is that same-team ties are resolved by that team's decision of the order, but this is complicated when adding AI control. For now, if a tie occurs, just roll-off until it's resolved. And to do this, you will need to make sure that rolled iniative (after modifiers) is remembered after the initial order is decided.

### C2. Faction: does a summon inherit the summoner's `team`? And can summons turn hostile?
There's an existing `team` field (`None` = hostile to everyone). A summon almost always fights for its
summoner.

- Inherit the summoner's `team` (and `is_player_controlled`?) at creation.
- Some spells (losing concentration on certain summons, wild-magic, *Conjure* variants where the DM
  controls the creature) can make a summon **hostile** — model a team-flip, or ignore that tail?

**Recommendation:** inherit `team` (and controller flag) on creation. Support an explicit
"allegiance" field on the summon block defaulting to "summoner's team", so the rare hostile/neutral
summon is expressible without special-casing — but don't build the wild-magic-flip machinery until a
spell needs it.

**Your answer:**
> Recommendation is perfect. I had also thought about the possibility of odd cases where summons aren't friendly, but you've handled it well here. No reason to build all the machinery until we get to the spells that call for it.

### C3. Where do summoned creatures physically appear?
They need a position (the grid is real — coordinates, ranges, AoE all use it). Where?

- **Adjacent to the caster**, engine-chosen (nearest free cells).
- **At author/caster-chosen points within range** (like AoE placement — the caster already supplies a
  target point for those).
- **A fixed offset / within X ft of a chosen point** (5e's "within range, in unoccupied spaces").

**Recommendation:** **caster-chosen point(s) within the spell's range**, reusing the AoE
target-point mechanism, with an engine fallback to nearest free cells if no point is given; a horde
places into unoccupied cells around the point. Confirm, or say if engine-auto-placement adjacent to
the caster is enough for now.

**Your answer:**
> Recommendation is perfect. AOE is almost exactly how it works in the rules as written, with the simply additional requirement of being unoccupied. Hordes are an edge case, but your suggestion of just finding unoccupied cells is fine for now until I check the rulebook on it.

---

## D. Lifetime & teardown

### D1. Confirm summon lifetimes map onto the lifetime-scope model (spell doc §6.3)?
Summons bind to the same lifetimes as other effects: **concentration** (*Summon* line, *Conjure
Animals*), **fixed duration** (some), **until dismissed** (many), **permanent / until destroyed**
(*Animate Dead* once cast, *Simulacrum*). The §6.3 design says a lifetime scope *owns* revoke handles
and "dispose = walk handles in reverse." For a summon, **"revoke" means removing a combatant from the
battle** (roster + initiative + its ongoing effects), not just stripping a modifier.

**Recommendation:** yes — a summon is a grant owned by a lifetime scope; losing concentration or the
duration expiring disposes the scope, which removes the creature. This is the single biggest reason
§6.3 (lifetime scopes) should land before the summon family. Confirm.

**Your answer:**
> Recommendation is perfect.

### D2. Teardown semantics — what exactly happens when a summon dies or is dismissed?
Removing a mid-battle combatant is more than deleting a list entry:

- **Initiative:** remove its slot and fix `current_turn_index` (same pointer hazard as C1, in reverse).
- **Its own ongoing effects:** a summon may itself hold buffs/conditions/concentration — disposed with
  it.
- **Recursion:** a summon that itself summoned (or a summon holding *Armor of Agathys*) — teardown must
  cascade, with the same depth/re-entrancy guard as §6.4.
- **Death vs dismissal:** does a *killed* summon trigger on-death riders (yours or its own) before it's
  removed, while a *dismissed* one just vanishes? (BG3 summons dying can trigger effects; dismissed
  ones simply disappear.)

**Recommendation:** dispose bottom-up (its grants first, then the creature), route removal through the
same bounded work queue as other re-entrant events, and distinguish **death** (fires `ENTITY_DIES` →
on-death riders → then removal) from **dismissal/expiry** (silent removal). Confirm the death/dismiss
split matters to you.

**Your answer:**
> Rules get fiddly here. Death, dismissal, and destruction are all distinct occurences, with thier own unique triggers, which can overlap. For some clarifications, a creature reaching 0HP by any means almost always means death. Willful dismissal is not death, unless that creature very specifically has a reason to count it as such (such as some form of self-destruction mechanism). And some spells read as "when the creature is destroyed", which I would personally consider to unify both death and dismissal. My personal suggestion would be that destruction is not a discrete event, and anything with this wording simply subscribes to both the death and dismissal events. But the recommendation is good enough to work with.

### D3. What happens to summons when their lifetime outlives the encounter, or the summoner dies?
Edge cases worth a ruling:
- The **summoner dies** while concentrating → concentration ends → summon vanishes (falls out of D1
  automatically). Confirm that's the intent.
- **Combat ends** with summons still up (duration/permanent) — do they persist as entities, or is
  "combat" the only scope we model so they're dropped? (This sim may not have an out-of-combat state.)
- **Permanent undead** (*Animate Dead*) with no concentration — who owns their lifetime across
  encounters?

**Recommendation:** for now, model only the in-combat scope: summoner death ends concentration-summons;
non-concentration summons persist until combat ends, then are dropped with the encounter. Defer
cross-encounter persistence until there's an out-of-combat model. Confirm.

**Your answer:**
> Recommendation is perfect - there are no plans for anything but individual comabt scenarios right now. Anything with a short lifetime (minutes/turns) needs counting, probably in a manner related to those lifetime tags you mentioned earlier. They'll need to listen for the creature's own turn ending and tick down, then handle dismissal/death when time runs out.

---

## E. Control & action economy

### E1. Does commanding a summon cost the summoner anything?
In 5e many summons require the caster to spend an **action or bonus action to command** them (*Spiritual
Weapon*: bonus action to move+attack; the *Summon* line: the creature acts on its own but you use a
bonus action to command; *Flaming Sphere*: bonus action to move it). Others act freely once summoned.

- Model the command cost (a summon block declares "requires bonus action to direct").
- Ignore action-economy-of-command for now; summons just act on their initiative.

**Recommendation:** since action economy for *commanding* interacts with the (absent) AI/turn-driver,
**ignore it for now** and record it as deferred — but keep a `command_cost` field in the block schema
so it's expressible later without a redesign. Confirm you're happy deferring.

**Your answer:**
> Recommendation is perfect for now. Keep it in mind as a possibility, and make sure not to write out the possibility, but don't bother actually inclduing all the summon-command machinery until we've worked out what an AI taking a turn actually looks like.

---

## F. The exotic tail (where the model earns its keep)

### F1. Simulacrum — how deep does "a copy of a creature" go?
Simulacrum creates a **duplicate of a creature**: half its max HP, its own separate resources, it
**can't regain spell slots**, and it's a distinct entity that persists until destroyed. This is the
pathological case — it reads a *live creature or its statblock* and derives a modified entity from it.

Questions:
- Copy from a **live `Entity`** (current HP/state) or from the **immutable `StatBlock` template**?
  (5e copies the creature as it "knows" it — template-like.)
- How faithfully must the copy's **spell list / actions** carry over, given those are data on the
  statblock already?
- Do we need the "**can't regain resources**" rule now, or is a half-HP copy with normal resources an
  acceptable first cut?

**Recommendation:** copy from the **`StatBlock` template** (clean, deterministic), carry actions/spells
as-is, apply a half-HP modifier and a distinct (seed-stable) id, and **defer** the "can't regain
slots" nuance behind a flag. Treat Simulacrum as the acceptance test for "derived-from-entity"
summoning. Confirm the template-copy approach.

**Your answer:**
> Recommendation is good for now. We can nitpick once we've got an implementation.

### F2. The blurry line: summoned *creature* vs positioned *effect-object*.
Several "summons" are arguably **not creatures** but persistent effects with a position and a small
behaviour: *Spiritual Weapon*, *Flaming Sphere*, *Cloud of Daggers*, *Bigby's Hand*, *Moonbeam*. They
occupy space, move, and deal damage, but have no HP, no saves, and don't "act" independently — the
caster operates them. Deciding which side of the line each falls on shapes the block family: a *real
entity* goes through the roster/initiative machinery above; a *positioned effect* is closer to a
persistent AoE that follows a point and fires on the caster's turn.

- **One mechanism:** everything is an entity (some entities are just "objects" with no turn/HP).
- **Two mechanisms:** creatures (roster/initiative) vs positioned effects (a lifetime-bound, movable
  emitter that acts on the caster's turn) — most of the "acts on your turn" cases (C1) become effects,
  not combatants.

**Recommendation:** **two mechanisms.** Reserve entity-creation for things that genuinely need HP, a
statblock, and a turn (elementals, undead, beasts, Simulacrum); model *Spiritual Weapon* /
*Flaming Sphere* / *Moonbeam* as **positioned, lifetime-bound effect emitters** (a persistent AoE with
a position the caster can move) — that keeps the initiative/pointer complexity out of the common "acts
on your turn" cases and reuses the AoE + lifetime machinery. This is probably the most important call
in this doc — where you draw this line determines how much of summoning is "hard."

**Your answer:**
> Recommendation is good. Hazards and objects like wall of fire, moonbeam, spike growth, etc, are decidedly not entities. They have no iniative, individual action, or even a fraction of the stats that real combat entities do. I almost asked to define a more generic system for non-entity objects that could also define things like bottles and tables for cover and improvised weapons, but that's definitely scope creep. For magic, positioned effect is the right way to handle this kind of thing. For the BG3 intuition, *most* of these are definitely not entities. The one major exception is guardian of faith, which basically acts as an entity with a heuristic (hit the closest non-ally in range) instead of an AI. But that's an edge case, and easy enough to add later on when the behaviour is so rudimentary.

---

## G. Anything else / your BG3 intuitions

Free space. Anything BG3 (or tabletop) does around summons — placement, control, initiative, death,
dismissal, "acts on your turn" vs "own turn", the concentration link — that felt right or wrong, and
any specific summon spell you want to use as the forcing function for the design.

**Your answer:**
> Most notes have been mentioned. Keep to the 5e rulings (summons have their own turn) vs 2024 edition rulings (many simplifications, summons act with or right after their summoner). Split behaviors may be necessary for combatants that are dead/incapacitated which should maintain position in iniative order in case of revivify/resurrection (but skip turns) versus combatants that are truly *gone* (dispelled, destroyed(constructs), banished, disintegrated, etc) and should be entirely removed from turn order.

---

_Feeds [SPELL_SYSTEM_DESIGN.md](SPELL_SYSTEM_DESIGN.md) §6.12 (the frontier note) and §7 (design task
before stage 4). Once answered, I'll turn these into an `entity_lifecycle` block-family design section
in the design doc, and note any prerequisites (seed-stable ids, pointer-safe initiative insertion,
lifetime scopes) that must land first._
