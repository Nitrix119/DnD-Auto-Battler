# Agent Arena — Open Decisions & Questions

> **Purpose.** The decisions about the agent framework where I most want *your* input before
> building further, collated so you can answer in one pass. Companion to
> [AGENT_ARENA_PLAN.md](AGENT_ARENA_PLAN.md) (the architecture) — this is the "vision &
> intent" layer that shapes how the pieces behave. Where I have a view it's marked
> **Recommendation**; otherwise options are laid out neutrally.
>
> **How to respond:** write under each **Your answer:** line (the `> _…_` block). "Agree" /
> "recommendation is fine" is a complete answer — I'll only follow up where you push back or
> add nuance. The ones gating the very next code slice (tools/executor, agent interface, turn
> driver, match runner) are flagged **⛳ gates next slice**.
>
> **Where we are:** the read-only sensory layer is built and green (observation, information
> policy, legal-action assembly). Next is the "motor" side — how an agent actually *acts* and
> how a match runs. Most gating questions below are about that.

---

## A. Vision — what are we actually measuring?

### A1. What is the arena *primarily* for? ⛳ (sets every other priority)
Different primary goals pull the design in different directions, so I want the ranking.

- **(a)** **Benchmark model skill** — "which model/prompt plays 5e combat better?" Priorities:
  fairness, determinism, clean metrics, many matches.
- **(b)** **Research information asymmetry** — your stated interest: how does hiding HP/AC/etc.
  change play and outcomes? Priorities: the policy knob, paired experiments, metrics.
- **(c)** **Watchable spectacle** — fun to observe two agents duel. Priorities: narration,
  the web spectator, readable transcripts.

**Recommendation:** (a) and (b) are the real goals and they share almost all machinery —
build for both; treat (c) as a later nicety (the web bridge). If you had to rank, I'd guess
(b) is the one that's *yours* and (a) is the substrate that makes (b) rigorous.

**Your answer:**
> (a). The primary intention of the project has shifted for me, despite originally being intended just for fun or to play manually against the AI. The main intention is for model benchmarking, since I think this is an interesting and novel application.

### A2. Neutral referee, or coached strategist?
How much D&D *strategy* do we put in the system prompt? This defines what "skill" means.

- **Neutral:** tell the agent only the rules of engagement and the objective; let its own
  reasoning supply all tactics. Measures the model's *raw* tactical ability.
- **Coached:** include tactical guidance ("focus fire, protect low-HP allies, hold
  concentration"). Measures how well it *executes* known tactics; compresses the skill gap.

**Recommendation:** neutral by default — it's the more honest and interesting measurement,
and coaching is a knob we can add later as its own experiment (coached-vs-neutral is itself a
fun matchup). Keep the system prompt to role + rules + objective.

**Your answer:**
> Recommendation is perfect. Part of the interesting part is forcing the models to figure out sensible strategies for themselves.

### A3. Default visibility of enemy *capabilities* (not just HP/AC)?
The information policy currently gates enemy HP/AC/resources/conditions/slots. A separate
question: should an agent see *what an enemy can do* — its attacks and known spells? Today the
observation does **not** reveal enemy action lists (you see the goblin, not its stat sheet).

- **Hidden by default** (realistic — you learn an enemy's abilities by watching them used).
- **Revealed by default** (perfect information — simpler, more "chess-like").
- **A policy toggle**, hidden by default, like the other fields.

**Recommendation:** hidden by default, exposed via a policy toggle (`reveal_enemy_actions`).
It fits the info-asymmetry theme and is realistic; a match can opt into full disclosure. The
agent still *observes* abilities as they're used (via the combat log).

**Your answer:**
> Recommendation is perfect. Real combat does not allow players to know the capabilities of their opponents, only remember what damage they've done.

---

## B. Agency model — who controls what, and how

### B1. One agent per **team**, or one per **entity**? ⛳
A fundamental shape decision that gates the match runner and turn driver.

- **Per team (one brain per side):** Agent A controls *all* of team A's creatures whenever any
  of them is the active combatant; Agent B likewise. This is the clean "Player A vs Player B"
  benchmark.
- **Per entity (one brain per creature):** each creature has its own agent; allies don't share
  a mind and must coordinate implicitly. More chaotic, more like a real table of players.

**Recommendation:** per **team** as the default (cleanest comparison, one identity to attribute
a win to), with the interface written so per-entity is a later option (a team agent is just an
entity agent whose "self" rotates). Most benchmarking wants one brain per side.

**Your answer:**
> One per team. It could be interesting later to have multi-agent teams and see how they try to cooperate and deliberate strategy, but this is not a priority right now.

### B2. Turn granularity: one action at a time, or plan the whole turn? ⛳
When it's an agent's turn, does it…

- **Act one step at a time:** issue one tool call, see the result (hit/miss, damage, new
  positions), then decide the next — until it ends its turn. Truer to how D&D plays ("swing,
  see it land, then move"); better decisions; richer transcript. **Costs more API round-trips
  per turn.**
- **Plan the whole turn at once:** emit all of a turn's actions in one response. Fewer API
  calls (cheaper), but the agent can't react to a miss or a kill mid-turn.

**Recommendation:** one action at a time, capped by a per-turn action guard. It's the bigger
quality lever and the more faithful model. Flagging the **cost** tradeoff explicitly given
your API-spend caution — if cost dominates, whole-turn batching is the cheaper dial.

**Your answer:**
> Recommendation is perfect. I'll monitor costs, but accurate benchmarking is the goal, and restricting the agents' ability to react mid-turn for the sake of cost would harm the authenticity.

### B3. What does the agent remember between turns? ⛳
The API is stateless — we decide what history each turn's prompt carries.

- **Full raw thread:** accumulate every prior message/observation. Most context, grows without
  bound, most expensive, and eventually needs compaction.
- **Fresh prompt each turn:** rebuild from system + rules + *current* observation + a compact
  running **combat log** (what happened recently). Stable, cacheable prefix; bounded cost.

**Recommendation:** fresh prompt each turn with a compact event log — bounded cost, a stable
cacheable prefix, and the engine's own combat log is already a natural summary. The agent's
*own* prior reasoning within a single turn is kept during that turn's action loop, then
dropped. (This is also the cost-safe default.)

**Your answer:**
> The recommendation here is good, but I think some context of what they've seen the opponent do is important. At the very least, a short version of what the opponent just did would be good to provide. But a combat log/summary as suggested is a very natural way to provide this, while specific reasoning can be discarded. At most, maybe we could let the agent write short notes (strictly capped) to pass on to its next turn.

---

## C. The referee — enforcing legality

### C1. Ratify: static tools + validation + retry (not action masking)? ⛳
Recap of the plan's choice: a small fixed tool set (`attack`, `cast_spell`, `move`,
`end_turn`), the legal-options menu *inside* the observation, and the engine validates each
call — an illegal call returns a structured error the agent can correct. The rejected
alternative regenerates the tool schema each turn so only legal moves exist (breaks prompt
caching, unwieldy).

**Recommendation:** ratify static-tools + validation. Cheaper, stable prompt, mirrors the web
handlers, and your engine's precise `ValueError`s do the enforcing.

**Your answer:**
> Recommendation is perfect.

### C2. What happens when an agent keeps failing? ⛳
An agent might repeatedly emit illegal/garbled moves. We need a bounded response.

- Return the engine error, let it **retry**, up to **N failed attempts per turn** (I'd start
  N=3); after N, **auto-end its turn** and log the wasted turn.
- Harsher: after N, **forfeit the match**.

**Recommendation:** auto-end-turn after N=3 failures (logged as a quality signal — illegal-move
rate is a metric), **not** forfeit. Forfeiting on a transient hiccup adds variance and punishes
a model for one bad turn rather than for playing worse. Reserve forfeit for total protocol
breakdown (no parseable tool call at all across the retries).

**Your answer:**
> I think the suggestion is good, with perhaps a small tweak. Something like three consecutive failures, or five total. This could soften the amount that models that make minor typos suffer (assuming they can correct themselves), but still reasonably punish excessive mistakes. Open to debating this one, though - it's just an idea.

### C3. How transparent is resolution — does the agent see the dice? ⛳
After an action, the tool result feeds back. How much detail?

- **Outcome only:** "hit, 7 slashing" / "missed" / "save succeeded." (An observer's view.)
- **Full mechanics:** the d20 roll, modifiers, total vs AC, save DC vs roll. (A rules-lawyer's
  view — arguably meta-information a combatant wouldn't compute.)

**Recommendation:** outcome + concrete numbers the world reveals (hit/miss, damage dealt,
save success, target's new HP *if the policy reveals HP*). Treat the raw d20/roll math as
optional detail, off by default — it's cleaner and dovetails with the info-policy theme
(exact rolls are the kind of thing hiding is interesting for). Easy to toggle on.

**Your answer:**
> The recommendation looks great again here. The outcome should definitely be given, along with what the agent itself rolled. The values they're rolling *against* (AC, Spell Save DC, etc) should stay private unless the visibility settings state it should be, along of course with values like opponent HP.

---

## D. Rules knowledge & honesty

### D1. Does the agent get a 5e rules primer, or rely on its training?
Current models know 5e combat well. We can lean on that, or spell the rules out.

**Recommendation:** rely on the model's trained 5e knowledge; do **not** ship an SRD primer.
Include only a short "how *this engine* works" note (turn/resource model, that positions are
feet, how targeting/AoE aiming works). Keeps the prompt lean and tests genuine competence.

**Your answer:**
> The recommendation is not what I would have done initially, but I love it. It's a great test for the agents to rely on training to some degree, only explaining the things that are specific to the engine and agent interface.

### D2. Disclose the engine's current limitations to the agent?
This engine doesn't yet automate everything (no opportunity attacks / reactions on other
turns, free-form feet rather than a gridded battlemap, legendary actions out of the milestone-1
loop). An agent that plans around unmodelled mechanics will mis-play.

**Recommendation:** yes — state the engine's boundaries honestly in the system prompt (in the
spirit of CLAUDE.md §1 "model honestly, decline loudly"). The agent should know what will and
won't happen so it plans against the real simulation, not the tabletop it remembers.

**Your answer:**
> Recommendation is perfect - we want to be very clear what is missing, even if I hope to get a somewhat complete ruleset implemented eventually. But for the record, free-form was an intentional decision that actually replaced grid squares that were originally programmed in. Grid squares are a simplification for table play (along with rules like 3/4 of an AOE must cover a square to count there), but not canonical. See Baldur's Gate 3 - it also skips the grid.

---

## E. Matches, scoring & cost

### E1. Win condition and match termination for v1?
- **Win:** last team with a living creature standing (death match).
- **Termination safety valve:** a hard **round cap** (I'd start ~20 rounds); if hit, the match
  is decided on remaining team HP fraction (or called a draw).

**Recommendation:** death match + a round cap decided on HP fraction. The cap is also the
runaway-cost guard — no match can spin forever burning tokens.

**Your answer:**
> Recommendation is perfect. We can possibly lower the cap more after checking how long fights actually go. On a real table, I often don't see longer than 6-8 turns, but of course this is massively dependent on the size of fights, power of combattants, and sheer efficiency of players.

### E2. Which metrics matter first?
Beyond who won. All are cheap to compute from the transcript.

- **win-rate** over N seeded matches (the headline).
- **illegal-move rate** (a competence signal).
- rounds-to-win, damage dealt vs taken, resources/slots spent, HP remaining.

**Recommendation:** ship **win-rate + illegal-move rate** first; log the rest into the
transcript so we can analyze later without re-running (re-running costs tokens).

**Your answer:**
> Recommendation is perfect. Log everything useful, then metrics are as simple as finding new truths from the data we already have. No re-running LLMs every time we want a new metric if avoidable.

### E3. Live-test configuration (the one step that spends money) ⛳ (for step 7)
When we wire the first real Claude turn: model, thinking, effort, and hard caps. You've flagged
cost care, so this sets the guardrails.

**Recommendation:** `claude-opus-5` with adaptive thinking, **effort `medium`** for the first
runs (step down from the default `high` to save tokens while we shake out bugs), and hard caps:
round cap + max tool-calls/turn + an optional per-match token budget. First matchup: opus-vs-opus
to validate the loop, then try opus-vs-sonnet to see if the harness surfaces a skill gap. You
provide the key when we reach this step.

**Your answer:**
> Recommendation should be fine here, as long as the API bill doesn't look terrifying after a dozen battles. I've seen Opus 5 do hideously expensive things, but that's always been in Claude Code - this is a tremendously simpler environment with far less to do, so I really do not anticipate task eating $50+.

### E4. Provider-agnostic interface — confirm build-now-implement-later?
You picked "other providers." Plan: build the abstract `Agent` interface now with a concrete
**Claude** implementation; a non-Claude adapter (OpenAI, etc.) is added later, against the same
interface, when you want it. (Our Claude-API tooling only generates Claude code, so a non-Claude
adapter would be a separate, deliberate addition.)

**Recommendation:** confirm — design the seam now, implement Claude only, add others on demand.

**Your answer:**
> The important part to me here is that other providers (or stuff off OpenRouter, new cheap Chinese open-weight models, all that) are *viable*. As long as this isn't designed hyper-tailored to Claude in a way that would make it annoying to try others, we're fine. But Claude is good place to start since it's what I use most.

### E5. Anything you want captured that isn't here?
Free space — constraints, priorities, a specific matchup or scenario you want to see work first
(naming a concrete "this fight must run well" is a good forcing function), or cost limits I
should treat as hard.

**Your answer:**
> Nothing too strict. Priority is just to see something run as soon as possible, without skipping due process in making a well-designed framework. And I want to be able to watch the battles in some regard using the web interface, even if *playing* them using it has been massively sidelined. Maybe something like a replay feature? Since we're logging everything anyway, we could throw the action log and RNG seed (or just read the rolls and not even do RNG) so that I can see how a battle played out. This would also be cool in future if I put it online, since it would let me have a little replay button to let people watch the newest battles.

---

_Companion to [AGENT_ARENA_PLAN.md](AGENT_ARENA_PLAN.md). Once answered, I'll fold the decisions
into the plan doc's relevant sections and use them to build the next slice (tools/executor →
agent interface → turn driver → match runner), leaving the live LLM step for when you've set up
a key._
