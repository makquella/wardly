# Live advice audit (0.59.0, re-audited in 0.60.0)

Audit of the realtime coach against a review of match `9054793282` (Phantom
Lancer, 28 logged cards) and two other real recordings. What was changed, which
causes are confirmed, what stays open, and how to re-run the check.

## 0.60.0: the Phantom Lancer recording, rules re-audited

The recording of match `9054793282` (Phantom Lancer, `2026-10-21_0929`, 28
logged cards) was replayed through the whole live path. Everything below about
it is a replay, not a specification. The 0.59.0 sections further down are kept
as they were written (that version did not have the recording).

### How the replay joins a card to its snapshot

- Recordings up to 0.59 stamped a GSI line *after* publishing it, so the
  snapshot a card was decided on can carry a later `w` than the card (01:16:
  card `w` 3221.64, stunned snapshot 3221.12, unstunned 3221.66). The review
  shows the nearest earlier snapshot and, within 0.05 s after, the racing one.
  From 0.60 a GSI line is stamped at arrival and keeps the snapshot's own
  time (`ts`), and an advice line names it (`snap`), so the join is exact.
- The recorder also stores every change of the blocking flags and
  `has_debuff`, even inside one clock second (a stun shorter than a second
  was lost before).
- `--review` polls the current code at each logged card's own `w` (no
  window of seconds: a ±4 s match had paired the own Doppelganger at 19:21
  with a real enemy stun at 19:22), and lists separately the cards the
  current code adds and the cards it withdraws while held.

### The 28 logged cards, 0.60.0 at the same moment

«Now» is the current code at the card's `w`: `new` (a card at that moment),
`held` (the card shown then), or nothing with the gate that holds it.

| Time | Logged (0.58 live) | 0.60.0 at that moment | Why |
| --- | --- | --- | --- |
| 01:16 | Faerie Fire now, «seconds left» | nothing at 01:16 (stunned); 01:17 Faerie Fire now, after the stun; no projection | the card waits for a snapshot where it can be pressed |
| 03:16 | Save mana for the escape | Low mana limits your spells (W not learned) | learned escapes only |
| 05:14 | Faerie Fire, -32 % | Use Doppelganger now to get out | the escape is ready and wins over a heal |
| 05:37 | Do not re-contest without regen | held (same low-HP episode) | one card per episode |
| 05:52 | Faerie Fire again | the Doppelganger card held | no repeat while recovering |
| 06:27 | Faerie Fire, -33 % | Faerie Fire now (new fall after recovery) | kept |
| 07:00 | Use Tango (eaten at 06:56) | Leave the wave now and reset HP | Tango running is not asked again |
| 09:15 | Drop the wave, -53 % | kept | kept |
| 09:22 | Death from low resource | After respawn, avoid committing until your escape is ready | entry HP 81 %: not a low-resource death |
| 10:15 | Leave the pressured lane | 10:19 Avoid risky trades until Doppelganger is ready (back in 10 s) | the escape's state decides; 4 s later after the 09:14 disable card |
| 11:00 | Buy TP | kept (11:05) | kept (a 0.8 s stun card at 67 % HP had held it back in an intermediate build: the danger gate below removed it) |
| 12:30 | Wand + leave, 16 charges | Use Doppelganger now to get out, then Magic Wand | 0.59 had lost the Wand; it is named with the escape |
| 14:20 | Reset before another lane, -32 % | kept | kept |
| 16:50 | Keep farming: 422 GPM | nothing | filler (a statistic, no decision) |
| 18:10 | Manta after the disable | 18:11 Use Manta Style now: it removes the silence | the status at 18:11 is a silence: Manta is pressable now (pressed 0.0 s after) |
| 18:13 | Wand + leave, 20 charges | Use Magic Wand now, then step back | kept (0.59 had lost it) |
| 18:33 | Two deaths in the jungle by the river | Use the respawn time to choose a safer route | 6.7k units apart: no repeated-place claim |
| 19:21 | Manta after the disable (own W) | nothing | own phase (Doppelganger, 0.5 s, no HP lost) |
| 21:04 | Buy TP | nothing at 21:04; the TP card came at 20:33 and was withdrawn at 20:59 when a fight started | kept, earlier |
| 23:48 | Manta after the disable (own W) | nothing; 23:52 Use Manta Style now: it removes the silence | own phase, then the real silence |
| 23:55 | Manta to escape, -65 % | kept | kept |
| 26:25 | Stay alive: 3-kill streak | nothing | filler |
| 28:25 | Buy TP, 9 min | nothing at 28:25; the TP card came at 26:53, withdrawn at 28:34 by a fight | kept, earlier |
| 30:19 | Farm Bloodthorn vs PA | «Your team is 8 kills ahead: group up and take a tower» held (shown 29:53) | the Aegis is up with 3 allies: the tower, not farm |
| 31:43 | Do not show deep | After your kill: hold the next engage until Doppelganger is back | allies stay next to him (steady 2 s): no lone deep showing |
| 32:28 | Buyback first: 1338/1824 | nothing | the Aegis lasts 83 s more (pickup seen) and the base is safe |
| 33:02 | Keep the Aegis unless worth it | kept, with «expires in about 49 s and 3 allies are next to you» | Aegis facts |
| 33:08 | After respawn, avoid the route (Aegis lost) | nothing; 33:14 «Second life: hold the next engage until Doppelganger is back in 2 s» | revive, not a death |

Cards the current code adds in that match (no logged card of the family
within 10 s): post-disable cards at 05:17, 07:18, 09:14 and 12:40 (each a
real stun with HP falling to 7-51 %; Doppelganger pressed 0.5 s after at
09:14 and 12:40),
readiness at 18:17, 31:36, 33:14, the TP cards at 20:33 and 26:53, the kill
lead at 29:53, and a buyback card at 33:52 (Aegis gone, 1160/2066). Plan
cards (map hints): 06:35 «+1 last hit from 5:05 to 6:35, HP down to 12 %, 2
enemies around you», 24:34 «Fight over 5–1, 43 % HP», 28:51 «Aegis until
33:51, 3 allies with you», 32:17 «Fight won 6–0: their T3 in the mid lane»
(the tower fell 17 s later). Withdrawn while held: 20 cards (7 superseded by
a fight, 6 action done, 3 recovered, 2 respawned, 1 cannot act now, 1 life
lost). Cards in the match: 39 in 0.59.0, 36 now (a count says nothing by
itself; the table above is the check).

Disable cards in this match, 0.59.0 → 0.60.0: 13 → 6. The 7 removed were
short stuns (0.6-1.6 s) at 80-94 % HP losing 0-13 % with nothing after
them. The 6 kept all had HP at 7-51 % around the stun or 29-60 % lost in it;
in 4 of them the named tool was pressed 0-0.5 s after the stun. An
intermediate build lost the 09:14 one: the danger gate correctly waited for
HP to drop, and then the same-action game-time spacing (meant for coaching
repeats) held it 116 s after the 07:18 card; disable cards are now exempt
from that spacing like low-HP cards (bounded by the danger gate and one card
per stun).

### Rules re-audited with counterexamples

| Rule | 0.59.0 | Counterexample | 0.60.0 | Test |
| --- | --- | --- | --- | --- |
| Own phase | any own cooldown within 1.5 s of the onset, at most 5 s | real recordings: Spirit Lance, a Wand, Phantom Edge, Blade Fury, Quelling Blade started next to enemy stuns, some with HP lost | only mechanics measured to set `stunned` (Doppelganger 1.0 s, Manta 0.1 s, Metamorphosis 0.35 s) count, for their duration + 0.6 s sampling; cast 1.0 s before to 0.6 s after the onset; then judged again; StatusWatch runs on the wall clock (game time ticks whole seconds) | `test_a_spirit_lance_cast_next_to_a_stun_is_not_an_own_phase`, `…_outlasts_the_phase_is_judged_again`, `test_manta_with_an_enemy_stun_on_top_is_enemy`, `test_an_own_cast_long_before…` |
| HP lost in a status | from the first flagged snapshot | a stun and a nuke land together | from the snapshot before the onset | `…short_stun_at_high_hp…` (the nuke case) |
| Death accounting | counter rise = death; alive drop without it = revive (`revive_unknown`) | late counter, a counter missing after a reconnect, a gap with two deaths, a stand-up with no revive item | an alive drop without a rise is `unresolved` (or `reviving` with Aegis/Reincarnation) until settled: a late rise (death, `late`), a respawn timer > 6 s or 3 s dead (8 s with a revive expected) or a return at the fountain (inferred death `not_seen`, confirmed by a later rise, never counted twice), standing up within 600 units (`aegis_revive` with the Aegis gone, `reincarnation` with its cooldown started, else `revive_unconfirmed`: no second-life card); deaths across a gap > 10 s have no place; the last counter is kept across payloads without it | 7 tests in section 3b |
| Aegis vs buyback | Aegis held → no buyback card | an Aegis of unknown age (late recording), 20 s left, base under threat | only with a known timer ≥ 60 s and no base danger | `test_an_aegis_of_unknown_age_or_about_to_expire…` |
| Allies near | any ally on this tick's minimap within 1200 | an ally running past; a group outnumbered | an ally who stayed 2 s (by name, reset by a 3 s gap), and visible enemies around not outnumbering the group | `test_an_ally_crossing_for_one_tick…`, `test_a_steady_ally_against_more_visible_enemies…` |
| Repeated deaths | three at one spot or two close in 8 min = «change your route» | three deaths at one tower in team fights | the same place is `REPEATED_PLACE`; a repeated mistake needs the deaths alone (no steady ally) and away from an objective; no minimap = unknown = no mistake claimed. Thresholds: 2500 units is a camp and its approaches, 8 min a few respawn cycles, 3 at a spot because 2 at a contested tower are normal | 3 tests |
| Readiness | «go in again once W is back» after any kill | W off cooldown is availability, not a reason; a multi-kill gave one bypass per kill | «hold the next engage until W is back», only with an enemy within 2000 or 15 % HP lost in 10 s, one gate bypass per 60 s | `…says_what_to_hold`, `…no_fight_around…`, `test_kills_in_a_row_are_one_readiness_moment` |
| Fresh numbers | drift < 150 gold kept the card with its old numbers | 1338 shown while the player has 1438 | the decision keeps its tolerance; the text is re-rendered with this snapshot's gold, cost and Wand charges; the voice key leaves the reason out, so a refresh is not spoken again | `test_a_held_card_within_tolerance_shows_this_snapshots_numbers`, `test_more_wand_charges_refresh…` |
| Post-disable card | any enemy disable with a tool | 0.6-1.6 s stuns at full HP (7 cards in this match) | only with HP ≤ 50 % or ≥ 15 % of max lost in the status (re-checked every snapshot); exempt from the same-action game-time spacing | `test_a_short_stun_at_high_hp…`, `test_the_same_disable_card_two_minutes_later_is_a_new_stun` (an invariant: the synthetic case does not reach the spacing gate, the real replay at 09:14 does) |
| One disable card per stun | — | an 18 s chain | already held by the shown card and the tactical-state dedup; an extra episode gate was written, changed nothing measurable and was removed; the invariant is a test | `test_one_disable_card_per_stun_even_a_long_chain` |
| Voice | — | a tip skipped while busy | no queue: spoken only if a later poll still returns it (revalidated) | `voice.test.js` |

### What 0.60.0 adds: plan, lane, items, fights, Aegis

`app/live_plan.py` keeps one short-term plan (goal, basis, next step, done and
cancel conditions); a stronger plan replaces a weaker one, a finished plan
keeps how it ended. A card (a map hint, EN/UK) comes only when the plan
starts, that is when the best action changes.

| Plan | Starts when | Next step | Ends when | Not done (and why) |
| --- | --- | --- | --- | --- |
| `lane_recover` | a core, 3:00-10:00, ≤ 1 last hit in 90 s alive, HP ≤ 50 % or 2+ enemies within 1600 | the tower's last hits, ask a support | 3 last hits in a minute (done), laning over, death | no «go to the jungle»: GSI shows neither the creep equilibrium nor whether the hero clears camps at its level (both named in `basis.unknown`) |
| `deliver_item` | an active item (`SAVERS`) or its recipe 30 s in the stash, alive | the courier | out of the stash, 3 min | passive or stat items (Skadi, an Aghanim's that changes no press) start nothing |
| `after_fight` | no enemy within 2500 for 6 s after one was (within 30 s), the kill score moved | won ≥ 2 kills with a steady ally and an enemy tower within 3000: the tower; else at ≤ 50 % HP: recover | tower down, HP back to 80 %, 45 s, enemies back in number, death | no result from missing markers; the score counts kills anywhere on the map, so a fight's tally can include a kill elsewhere |
| `aegis_window` | the Aegis picked up with its timer known (≥ 60 s) | with steady allies: the next tower or objective; alone: group up | the Aegis gone | a second life after its revive is the readiness card's |

TP channel: GSI has no channel flag; a TP whose cooldown just started with the
hero standing (≤ 150 units, ≤ 4 s) is channelling (`teleporting`). Cards that
name no tool, urgent or not, wait; a card naming a tool still passes.

### Hero and mechanic coverage (0.60.0)

How each mechanic is checked: **real** (a replayed recording shows the case),
**test** (synthetic regression in `test_live_realtime_regressions.py`,
`test_live_hero_mechanics.py` or `test_live_plan.py`), **review** (the rule
was read against the mechanic, no test), **unchecked** (nothing yet).

| Mechanic | Heroes / items | Real | Test | Review only / unchecked | What the coach does |
| --- | --- | --- | --- | --- | --- |
| Own hidden phase, measured | PL Doppelganger, Manta, TB Metamorphosis | PL (23 Doppelganger phases), Jugg/TB (15 Manta, 3 Metamorphosis) | own phase; longer than its duration re-judged; Manta + enemy stun = enemy; cast 3 s earlier proves nothing | — | `own_phase` only within the measured duration + 0.6 s |
| Own hiding, not measured | Puck Phase Shift, Ember Sleight of Fist, Storm Ball Lightning | — | `stunned` with their cooldown starting is `unexplained`, never `enemy` | Lifestealer Infest, Void Spirit Dissimilate: review | no order to spend an item; no claim it was an enemy |
| Own phase without a flag | Juggernaut Omnislash | Jugg (never `stunned`) | no disable card | — | nothing to classify |
| Coincident own cast | Spirit Lance, Wand, Blade Fury, Quelling Blade next to a real stun | PL, Jugg (with HP lost) | Spirit Lance + stun ≠ own phase | other casts: review | enemy evidence decides |
| Aegis revive | Aegis | PL 33:08 | revive, no death, second life only on the spot | — | `aegis_revive`, readiness with a fight around |
| Reincarnation | Wraith King | — | revive with its cooldown started | — | `reincarnation` |
| Unconfirmed stand-up | Phoenix Supernova, unknown revives | — | `revive_unconfirmed`, no second-life card | Supernova's egg state: unchecked | no death, no claim |
| Delayed outcome | Oracle False Promise, Shallow Grave | — | HP healed back is no death | Shallow Grave: review | counter decides |
| Late / missing counter, gaps | any | PL 09:22 (counter + `respawn_seconds` 0 in the first dead snapshot) | late counter, never-shown counter (inferred, confirmed once), reconnect without the field, gap with two deaths | — | `unresolved` until settled |
| HP cost | Huskar, Phoenix, Soul Ring | — | slow cost is no burst | Phoenix Sun Ray drain: review (a real drain still counts as HP lost) | no fast-fall card from a small cost |
| Max-HP change | Armlet, Treads, Morphling shift | PL (Treads 780↔1000↔1044) | same share = no damage; Armlet toggling no fast fall | Morphling: review | HP net of max-HP change |
| Mana as life / variable cost | Medusa, Leshrac, Storm | — | — | unchecked | low mana names only learned escapes |
| Clones, linked units | Meepo, Arc Warden, Lone Druid | — | own clone on the minimap is no ally | Spirit Bear, Meepo linked death: unchecked | main hero only; counter decides |
| Illusions | PL, Naga, TB | PL (illusions not in GSI) | — | limit | no illusion micro advice |
| Ability swaps, refresh | Rubick, Invoker, Refresher | — | swapped-in spell on cooldown is no cast; refresh is no cast | Morphling morph: review | casts only from ready → running |
| Channels | TP, Black Hole, Freezing Field | — | TP channel seen (cooldown start + standing); no-tool cards wait | ability channels: unchecked (no flag, no cooldown shape) | `teleporting` holds move cards |
| Global travel | Nature's Prophet | — | (0.59) | Io, Underlord: review | Teleportation replaces the TP card |
| Roles | core / support | PL offlane, Jugg, TB | support gets no lane plan | — | lane plan only for cores |


### Juggernaut and Terrorblade, 0.60.0

JUGG_TB_PLACEHOLDER


## Data and limits of the conclusions (0.59.0)

- **The primary recording `2026-10-21_0929_9054793282.jsonl` was not available**
  to this work (not attached, not on disk). Its 28 episodes were used as the
  specification of synthetic scenarios; nothing below claims that this match
  was replayed. To check it: see [Re-running](#re-running).
- Two real recordings were replayed through the whole live path, old card
  (logged `k=advice`) next to the new decision: Juggernaut, match
  `9042382595` (5275 GSI snapshots, 41 cards), and Terrorblade, match
  `9042342539` (3906 snapshots, 27 cards). They stay on the player's computer;
  no fragment is in the repository. The tests are synthetic payloads in the
  same shape, each labelled with the real moment it copies.
- `w` in a recording is `time.monotonic()` for both GSI and advice lines, and
  the lines are in `w` order (0 order violations in both files). The evidence of
  a logged card is the nearest preceding GSI line; several snapshots share one
  clock second, so the clock alone is not a join key. Advice records now also
  carry the `basis` of the snapshot the card was decided on.
- GSI is no combat log: no modifier names, no caster, no enemy items, no team
  readiness. Statuses, deaths and "done" actions are inferred and every
  inference carries its evidence and confidence.

## What changed in code (0.59.0)

| Area | Module | Change |
| --- | --- | --- |
| Status source | `app/status_source.py` (new) | Classifies a stun/hex/silence/mute as `own_phase` (own cooldown started within 1.5 s of onset, no HP lost, `stunned` only, at most 5 s), `enemy` (HP lost, or a debuff that appeared at/after onset — sticky for the episode), `unexplained` (`has_debuff` false, no HP lost, no own cast) or `unknown` (no `has_debuff` field: legacy treatment). |
| Normalization | `app/gsi_state.py` | `has_debuff` (missing ≠ false), active-slot `item_cooldowns` / `item_charges`, `tp_in_stash`; the player's own hero is removed from `ally_units` (GSI drew it with the ally circle in 150 snapshots of one match). |
| Life cycle | `app/match_memory.py` | An ordinary death needs the game's death counter to rise (it does in the same snapshot as `alive=false` in both recordings). `alive` lost with the counter unchanged is a pending life loss: `aegis_revive`, `reincarnation`, `revive_unknown` or `life_lost_unexplained`, kept in `life_events`, never in `death_events`. The legacy alive-drop death stays only for payloads without a counter. Aegis gone while alive is `aegis_gone_alive`. |
| Death pattern | `app/match_memory.py`, `app/player_service.py`, `app/live_tools.py` | `REPEATED_DEATHS` needs a previous death within 2500 units and 8 minutes, or three at one spot in a match; otherwise `MULTIPLE_DEATHS` (no route claim). Low-resource death uses the HP/mana the hero entered the fight with (best of the last 15 s), not the last tick. Count-only lines («change your route: 3 deaths this game») are gone. |
| HP measures | `app/match_memory.py` | HP change in absolute points net of max-HP change (Armlet, Treads, attribute shifts); "falling fast" also needs HP still dropping over the last 2 s. `hp_rise_3s` for recovery. |
| Done actions | `app/action_feedback.py` (new) | Consumable used = charges down while alive, not moved to backpack/stash, not sold (gold jump), no data gap > 3 s. `regen_active` for running Tango/Salve/Clarity/Bottle. Own cooldown starts as `recent_casts`. |
| Held-card validity | `app/advice_validity.py` (new), `app/advice_scheduler.py` | Each card gets a basis (snapshot clock, alive, named tool, cited gold/cost, wand charges). Every GSI observe and poll re-checks it and withdraws the card: `life_lost`, `respawned`, `action_done`, `cannot_act_now`, `stale_numbers`, `resolved`, `recovered`, `not_a_threat`, `superseded_by_threat`. A withdrawn card is reported as `withdrawn_advice` for 10 s; the overlay drops it and cuts its speech. |
| Async answers | `app/advice_scheduler.py` | An LLM refinement applies only to the card it was started for (`_card_serial`), never to a newer or withdrawn one. |
| Queue gates | `app/advice_scheduler.py`, `app/advice_ux_policy.py` | Urgent `DISABLED_STATUS` cards bypass the post-laning farm-category dedup and the 2-per-minute quota (both swallowed real «use Manta now» cards). Generic «keep farming» filler is not shown; the heartbeat stays silent without a decision. |
| Copy | `app/live_tools.py`, `app/post_laning_coach.py`, `app/recommender.py`, `app/advice_i18n.py` | No «at this rate you have seconds left»; no streak or raw-GPM cards; low-mana reason names only a learned escape (and says when it is short of mana now); Aegis card with known time left and allies next to you; readiness after a kill or a revive; TP in the stash; Nature's Prophet's Teleportation replaces the TP card; buyback reason from the current snapshot, no buyback lock while holding the Aegis; deep with allies is no lone deep showing. All new lines have Ukrainian. |
| Ability names | `app/ability_normalization.py` | `phantom_lancer_doppelwalk` → Doppelganger (PL's escape was invisible to every escape rule), plus `obsidian_destroyer_sanity_eclipse`, `nevermore_requiem`, `pangolier_gyroshell`. |
| Overlay | `frontend/launcher/overlay/app.js`, `voice.js` | Drops a withdrawn card instead of re-rendering it on a cooldown poll; `speaker.cancel(key)` cuts only that card's speech. |
| Replay tool | `scripts/replay_recording.py` | `--audit` (basis, status source, data age, withdrawals per card), `--review` (logged card vs current decision with the nearest earlier snapshot), `--until` (prefix), plain `.jsonl` input. |

## Causes

### Confirmed

- **3.1 Own phase as enemy control.** `decision_points.has_disabled_status` read
  any `stunned` as a disable, and `live_tools.disabled_copy` then named a tool.
  Real data, match `9042382595`: at 28:31 and 30:18 `stunned` appears in the
  very snapshot where Manta Style goes 0 → 34 s cooldown, HP full, no HP lost
  (at 30:18 a debuff was already present 2 s before the onset). At 9:22 a 3 s
  `stunned` with `has_debuff=false`, HP regenerating and no own cooldown: source
  unknown, still a «use Blade Fury» order. PL's 19:21/23:48 Doppelganger cards
  match the same sequence but were not replayed (no recording).
- **3.2 Aegis loss as a death.** `MatchMemory` recorded a death on any alive
  `true → false`, even with the counter unchanged, and classified any second
  death as `REPEATED_DEATHS` (`death_count >= 2`). An Aegis life loss therefore
  became a repeated-death card.
- **3.3 Stale buyback numbers.** `BuybackTracker` froze `{gold, cost}` at the
  purchase and held the signal 60 game seconds; `_buyback_reason` formatted the
  frozen pair whenever spacing let the card through. 1338/1824 (31:47) shown at
  32:28 is exactly that path. Not a cache, prompt or LLM: the LLM is off by
  default and the text is deterministic.
- **3.4 Repeat after a done action.** Nothing tracked consumable use;
  `low_hp_copy` listed Tango while its charge had just gone, and a low-HP
  episode restarted once HP briefly went back over 60 %.
- **3.5 Projection.** `hp_falling_reason` always added «at this rate you have
  seconds left» (11 of 41 cards in one match, 10 of 27 in the other), whether
  or not the HP was still falling; `hp_percent` deltas ignored max-HP changes.
- **3.6 Causality after death.** `LOW_RESOURCE_DEATH` read the last alive tick
  (always low); place patterns grouped deaths by zone label only, so 6.7k units
  apart counted as «the same place». On the Juggernaut recording all 5 deaths
  were «low resource» by that rule (last alive tick at 6, 8, 15, 8 and 1 % HP);
  the fight-entry rule leaves 1 (entered at 57 % HP with 23 % mana).
- **3.7 Team context.** `post_laning_risky_showing` used only the position zone;
  allies on the minimap were never read for it.
- **Found on the way:** PL's Doppelganger never matched its profile name; urgent
  disable cards were dropped by the post-laning dedup (`duplicate_post_laning`)
  and by the 2-per-minute quota (`rate_limit`), both seen in replay.

### Hypotheses, open or refuted

- **3.8 «Faerie Fire now» during a stun (01:16).** Not reproduced: `low_hp_copy`
  already switched to the post-disable line when the deciding snapshot was
  stunned. Most likely the card was decided on the snapshot just before the
  stun and then held/spoken unchanged (the overlay speaks a held card on a
  later poll). Now the held card is withdrawn as `cannot_act_now` and the
  low-HP episode may speak again in the form that fits; on the Terrorblade
  recording this happened twice. Open until the original log is replayed.
- **«Async answer mixes action and reason» (3.3):** refuted for the default
  configuration (no LLM call); the refinement guard was tightened anyway.
- **`has_debuff` semantics:** observed true for enemy stuns with damage and
  false for own phases, but also true from an unrelated earlier debuff. Only a
  debuff that *appears* at the onset counts as evidence; a pre-existing one
  plus no own cast stays a medium-confidence possible enemy disable (a stun
  often lands before its damage). Unverified on other client versions.
- **Mana cost:** GSI sends no mana cost; «not enough mana» is inferred from
  «off cooldown, `can_cast=false`, not silenced/stunned».

## The 28 cards of match 9054793282 (0.59.0 specification, before the recording was available)

Expected decision of the current code for each card, from the mechanism that
now handles it. ✓ bug fix, ◇ policy change, = kept.

| Time | Old card | Now | Why |
| --- | --- | --- | --- |
| 01:16 | Faerie Fire now + leave, «seconds left» | ✓ no «now» while stunned (post-disable line, or withdrawn and re-issued after); no projection | executability, revalidation |
| 03:16 | Save mana for the escape | ✓ «Low mana limits your spells» (W not learned) | learned-only escape |
| 05:14 | Faerie Fire + leave, -32 % | = card kept; reason states the loss, no projection | |
| 05:37 | Do not return without regen | = kept (165/780 HP) | |
| 05:52 | Faerie Fire again | ✓ silent while HP is rising (recovering episode) | recovery |
| 06:27 | Faerie Fire, -33 % | = new fall after recovery speaks again | |
| 07:00 | Use Tango | ✓ Tango eaten at 06:56 is `regen_active`: not named again | done action |
| 09:15 | Drop the wave, -53 % | ◇ the Wand (6 charges, ready) is named when it is a ready saver (from 10 charges, existing rule); otherwise the line stays | unchanged rule |
| 09:22 | Death from low resource | ✓ entry HP 81 % → no low-resource cause | fight entry |
| 10:15 | Leave the dangerous lane | = kept | |
| 11:00 | Buy TP | = kept (or «bring it from the stash» if bought) | |
| 12:30 | Wand + leave, 16 charges | = kept; withdrawn once pressed | |
| 14:20 | Reset before another lane, -32 % | ✓ no «falling fast» once the drop stopped after W | still-falling check |
| 16:50 | Keep farming: 422 GPM | ◇ not shown (statistic, no decision) | filler |
| 18:10 | Manta after the disable (real) | = kept: debuff/damage make it `enemy` | |
| 18:13 | Wand + leave, 20 charges | = kept | |
| 18:25 | (none) | ◇ new: «After your kill: go in again once Doppelganger is back in 5 s. Manta Style is back in 21 s.» | readiness |
| 18:33 | Two deaths in the jungle by the river | ✓ 6.7k apart: no repeated-route card | proximity |
| 19:21 | Manta after the disable (own W) | ✓ `own_phase`: no card | status source |
| 21:04 | Buy TP (used at 19:20) | = kept | |
| 23:48 | Manta after the disable (own W) | ✓ `own_phase`: no card | status source |
| 23:55 | Manta to escape, -65 %, silence | = kept; no longer droppable by the minute quota | queue gates |
| 26:25 | Stay alive: 3-kill streak | ◇ not shown | filler |
| 28:25 | Buy TP, 9 minutes | = kept (an unresolved problem may repeat) | |
| 30:19 | Farm Bloodthorn vs PA | = kept (item plan unchanged; truncated reason not addressed) | |
| 31:43 | Do not show deep, enemies unknown | ✓ Axe ~250 and SF ~1160 units away: not a lone deep showing | team context |
| 32:28 | Buyback first: 1338/1824 | ✓ current numbers, and not shown while the Aegis is held | freshness |
| 33:02 | Keep the Aegis unless worth it | ◇ the card adds time left (only if the pickup was seen) and allies next to you | Aegis facts |
| 33:08 | After respawn, avoid the route (Aegis lost) | ✓ no death, no card while reviving; then «Second life» readiness if W is on cooldown | life cycle |

## Real recordings, before and after

Logged card (old version, live) vs the current code on the same snapshots.

| Measure | Juggernaut 9042382595 old → new | Terrorblade 9042342539 old → new |
| --- | --- | --- |
| Cards | 41 → 56 (8 hero-gameplay tips the recorded version did not have, 3 readiness cards, disable cards the old gates dropped) | 27 → 35 (8 hero-gameplay) |
| «seconds left» projections | 11 → 0 | 10 → 0 |
| Count-only «change your route: N deaths» | 6 → 0 | 3 → 0 |
| Streak / raw GPM cards | 1 → 0 | 1 → 0 |
| Disable cards on an own phase or an unexplained stun | 3 (9:22, 28:31, 30:18) → 0 | 0 → 0 |
| Disable cards on enemy control (classification) | 5 → 10 (4 high, 6 medium confidence) | 3 → 3 (high) |
| «Low resource» death cause | 5 of 5 deaths → 1 (by fight entry) | — |
| Held cards withdrawn (no longer true) | — → 19 (7 action done, 5 respawned, 4 recovered, 2 cannot act now, 1 superseded by a fight) | — → 12 (4 recovered, 3 respawned, 2 action done, 2 cannot act now, 1 stale numbers) |
| Readiness after a kill | — → 3 («After your kill: go in again once Blade Fury is back in 18 s») | — → 0 |

Manual labelling of the cards above was done by the author from the
snapshots only, one match per hero; it says nothing about win rate and is not a
precision/recall estimate beyond these two games.

## Audit of mechanics and heroes (0.59.0; see the 0.60.0 matrix above)

Status: **covered** (rule + test), **partial** (generic rule, no hero test),
**limit** (GSI lacks the field; conservative fallback).

| Family | Examples | Status | Notes |
| --- | --- | --- | --- |
| Own hidden phases | PL Doppelganger, Manta, Omnislash, Puck Phase Shift, Ember Sleight, Storm Ball Lightning, Lifestealer Infest | covered (PL, Manta; Jugg/TB real data), partial for others | Generic rule (own cooldown start + `stunned` only + no HP loss), no hero names. A phase reported with other flags, or with the cooldown more than 1.5 s late, falls back to `unexplained`/`unknown`. |
| Banish, cyclone, ally saves | Astral Imprisonment, Disruption, Eul's, Snowball, Relocate | limit | GSI names no source. Self-cast Eul's starts an own cooldown (own phase); an ally's or enemy's banish without debuff/damage is `unexplained`: no order to spend an item. |
| Revive / delayed death | Aegis, Reincarnation, Supernova; Shallow Grave, False Promise | covered (Aegis, Reincarnation), limit (others) | Counter-based. Supernova and False Promise have no specific rule: an unexpected revive is `revive_unknown`, a long life loss without a counter is `life_lost_unexplained`. |
| HP cost | Huskar, Phoenix, Armlet, Soul Ring | partial | A one-step cost stops falling → no fast-fall; a continuous drain still triggers it (it is real HP lost). No causal «enemy burst» wording any more. |
| Max-resource changes | Morphling, Treads, Armlet | covered | Absolute HP net of max-HP change. |
| HP swap / fast restore | Sunder, Time Lapse, Time Walk | partial | Held low-HP cards are withdrawn when HP comes back; existing Sunder insurance card unchanged. |
| Mana-critical | Medusa, alternative resources | partial | Low-mana reason names only learned escapes; Medusa's Mana Shield logic unchanged. Mana costs unknown to GSI. |
| Charges / swaps / resets | Invoker, Rubick, Morphling, Refresher | partial | Tools are found by the current bar's raw/display name only; a stolen or replaced bar names nothing. Refresher resets show as cooldowns going to 0 (no special rule). |
| Clones / illusions / forms | Meepo, Arc Warden, Lone Druid, PL/Naga/TB illusions, Brewmaster | limit | GSI's hero block is the main hero; own illusions are `minimap_heroimage` (not allies, not used). Linked deaths (Meepo) are not modelled: the counter decides. No illusion micro advice is generated. |
| Channeling | TP, Black Hole, Freezing Field, Fiend's Grip | limit | GSI has no channel flag. «Step out» lines can still appear during a channel; not fixable without the field. |
| Mobility vs TP | Nature's Prophet, Io, Underlord | covered (Prophet), limit (others) | Only Teleportation is a TP substitute; Relocate/portal need an ally or a cast. |
| Roles | carry, mid, offlane, support | existing | Supports keep their decision set (`SUPPORT_DECISIONS`); readiness and TP copy follow existing coverage gates. |

Profiled heroes checked for ability-name matches: 39 (the item-stats heroes);
4 real mismatches fixed. Heroes without a profile get the safety-only set, and
all the generic rules above apply to them.

## Not implemented, and why (0.59.0; plan memory, lane, stash items and channels are covered in 0.60.0)

| Feature | Missing observation |
| --- | --- |
| Illusion/wave micro for PL («take the dangerous wave with illusions») | GSI does not report controlled units, their HP or orders. |
| Plan memory for the next 30–90 s (5.3) | Not built: intent cannot be read from GSI with confidence; the readiness card is the only forward-looking step. |
| Lane stagnation detector beyond the existing farm stall (5.1) | Not extended in this change; wave and creep state are not in GSI. |
| Item delivery vs readiness beyond TP | Only TP in the stash is handled; other stash items are simply not "ready" (active slots only). |
| Exact Aegis timer from a late recording start | Pickup time unknown → no timer (existing `roshan_timer` rule). |
| Channel-safe wording | No channeling field in GSI. |
| Enemy items, BKB, dispels | Not in GSI; never assumed. |

## Re-running

From `backend/` with the venv:

```
.venv/bin/python ../scripts/replay_recording.py <recording.jsonl[.gz]> --lang en \
    --audit audit.jsonl --review review.md [--until 33:20]
.venv/bin/python -m pytest tests/test_live_realtime_regressions.py
.venv/bin/python scripts/replay_check.py --text      # role goldens
```

`review.md` lists every logged card next to the current decision, the cards
added and the cards withdrawn while held. Keep recordings and their outputs
outside the repository.
