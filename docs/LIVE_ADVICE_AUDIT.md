# Live advice audit (0.59.0)

Audit of the realtime coach against a review of match `9054793282` (Phantom
Lancer, 28 logged cards) and two other real recordings. What was changed, which
causes are confirmed, what stays open, and how to re-run the check.

## Data and limits of the conclusions

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

## What changed in code

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

## The 28 cards of match 9054793282 (specification, not a replay)

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

## Audit of mechanics and heroes

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

## Not implemented, and why

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
