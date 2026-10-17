# Hero item plans

The live counter items (`backend/app/situational_items.py`) answer an enemy hero
by kind and position: a carry against evasion gets Monkey King Bar, whoever the
carry is. A hero item plan (`data/heroes/item_plans/<hero>.json`, loaded by
`backend/app/hero_items.py`) says what **this** hero buys instead. Terrorblade
is the first plan and the reference for the others.

The plan's counters come after the death patterns (BKB after deaths under stuns,
Linken's against a single-target disabler, Aeon Disk after bursts) and replace
the generic counters of the same family. `suppress` drops a generic counter that
does not fit the hero. Outside the plan's `positions` the generic counters stay.
The enemies come only from the enemy icon on the minimap (`enemy_heroes.py`):
allies and the player's own hero are never counted.

## How the 64 supported heroes get theirs

Three layers, so the same detail scales past one hero:

- **Numbers (automatic).** `.github/workflows/hero-stats.yml` runs
  `scripts/hero_item_stats.py --all --write` every Wednesday and by hand after a
  patch: `data/heroes/item_stats/<hero>.json` per supported hero in its usual
  position (OpenDota `lane_role`; supports unfiltered), from the open OpenDota
  Explorer (league games; a hero under 300 games in the patch is read from the
  previous patch on too). It holds the usual and tempo builds, the tempo net
  worth line, the skill build with talents, and for every enemy group each
  item's share against it and elsewhere, the lift and the win rates, with
  `candidates` (bought 2x+ as often against the group, 15%+ of 20+ games, a
  real item of 1500+ gold). A changed file is a pull request.
- **Mechanics (Valve).** Every item and ability a rule names is read from the
  Valve datafeed for the current patch (step 2 below).
- **Rules (judgement).** The candidates and the mechanics give a draft plan; the
  doubtful points (data against mechanics, thin samples, a minority with a
  better win rate) go to the player as 2-4 questions per hero. A hero's plan
  lands with its answers; `data/heroes/plan_coverage.json` lists the supported
  heroes still pending, and `tests/test_hero_plans.py` checks every plan the
  same way: each rule can fire and its family answers it, the minute gate holds,
  each reason renders in both languages on every screen, and no supported hero
  is left out of both lists.

## The checklist for a hero

0. **The numbers first.** `python scripts/hero_item_stats.py <hero>` prints the
   report (`--write` saves it): the win rate by the hero's gold at 20/25/30 min
   and the 85% line (the tempo curve), the item order in all won games and in
   the farmed ones, the skill build and each counter per enemy group. Every
   rule below is checked against it; a rule the high-rank games contradict
   needs a stated reason.
1. **The hero's build.** Read `data/meta/stratz_builds.json` (STRATZ
   Divine–Immortal, refreshed weekly) for the position: the core items and
   their minutes. A counter that is already in the build is "buy it earlier";
   one that is off the build needs a reason strong enough to change it.
2. **The mechanics, from Valve, for the current patch.** For every item the
   plan names, read `https://www.dota2.com/datafeed/itemdata?language=english&item_id=<id>`
   (ids from `/datafeed/itemlist`) and write the fact the rule depends on into
   its `basis`: e.g. Bloodthorn 7.41f gives True Strike to the hero's *controlled
   units* against the silenced target, which is why it suits an illusion hero.
   Hero abilities from `/datafeed/herodata?hero_id=<id>`. No rule from memory.
3. **The enemy groups.** Rules name groups from `hero_items.groups()`:
   `evasion`, `illusions`, `healing` (`draft_analysis.COUNTERS`), `escape`
   (`draft_analysis.ESCAPES`: escapes a silence stops, spell names from
   `/herodata`), `break` (`situational_items.BREAK_PASSIVES`), `jumpers`
   (`draft_analysis.JUMPERS`: heroes who jump onto a carry), `invisibility`,
   `illusion_clearers` (`draft_analysis.ILLUSION_CLEARERS`). A new group goes
   into those tables with its own check, not into one plan.
4. **The rules**, in order; the first that holds wins its `family`:
   - `why` — a short id of the reason;
   - `reason` — `{en, uk}`: one clause each, no final period, with the
     placeholders `{enemy}`, `{escape}`, `{spell}`, `{item}` (the tempo
     reason: `{item}`, `{net_worth}`). The draft card shows it as is, the death
     screen after «Why <item>:», the farm advice as its reason; the Ukrainian is
     matched to the English by `advice_i18n` itself, so no code changes per
     rule;
   - `item` / `name` — the OpenDota item key and the English name;
   - `enemy` (and `also`, a second group that must be seen too);
   - `minute` — from when the live farm advice may name it (the draft card
     early in the match ignores it);
   - `basis` — the build line or the Valve fact behind it.
   Put the more specific rule first (Bloodthorn for evasion **and** an escape,
   then Monkey King Bar for evasion alone).
5. **What does not fit.** A family the plan answers replaces the generic
   counter (Terrorblade's illusions family: Butterfly, no Maelstrom);
   `suppress` maps a generic `why` the plan leaves unanswered to the reason it
   is wrong for the hero.
6. **The usual build** (optional). `build` lists the hero's order in all
   high-rank won games ({item, name, unless}); it replaces the all-ranks
   OpenDota popularity for the farm advice when no counter or tempo holds.
   `unless` skips an entry another item answered (Terrorblade: no Pike once the
   Dragon Lance went into Hydra's Breath).
6b. **The skill build** (optional). `skills` keeps the hero's order of maxing
   the basic abilities, the first point and the talent picks per row, with
   their counts (the skill tips quote them: «463 of 634 games»), from the same
   games; it replaces the 3-5 recent pro games of `skill_build.py`. Check the
   order against the enemy groups too: if it does not change, one order stays.
   A talent row may carry `instead` ({name, label, enemy group, min}) for the
   lineup that changes the pick, and `never` for a talent the hero should not
   take.
7. **Tempo** (optional). `tempo.net_worth` is a curve `[[minute, net worth], ...]`
   from high-rank games of the hero: above it the hero wins most games (read the
   gold timelines in OpenDota Explorer, `player_matches.gold_t`; net worth is
   ~0.96 of that gold). With the player's own net worth over it (gold plus the
   items carried, `next_item.net_worth`), the counters wait and `tempo.items`
   go on. A player's GSI has no enemy or team net worth: the hero's own farm is
   the observed sign.
8. **The words.** Write `reason` in English and Ukrainian with the same
   placeholders; `tests/test_hero_plans.py` renders it on all three screens and
   checks the Ukrainian farm advice. A generic counter keeps its words in code
   (`map_hints.TIPS`, `death_screen.TEXT`, `post_laning_coach.SITUATIONAL_BECAUSE`).
9. **The scenarios.** Add the hero's cases to `backend/tests/test_hero_items.py`:
   each rule, the rule that must *not* fire (Anti-Mage is no escape for a
   silence: Counterspell), an owned item that answers the family, the minute
   gate, the death patterns still first, other heroes unchanged, and one live
   `/gsi` run to the overlay card.
10. **A real match.** Replay a recording on the hero (Settings → Keep match
   recordings for a week) and read which counter the card names and when.

## Terrorblade (7.41f, checked 2026-10-17)

Rules in order (the first that holds wins its family; one item per family):

| Family | Enemy lineup | Item | Why |
|---|---|---|---|
| evasion | Phantom Assassin or Windranger, and Queen of Pain, Storm Spirit, Puck, Ember Spirit, Void Spirit, Weaver, Mirana, Morphling or Faceless Void | Bloodthorn | Soul Rend: 5 s silence stops the escape; True Strike for his attacks and his illusions against the silenced target; passive pierce 40% |
| evasion | Phantom Assassin or Windranger alone (or with Anti-Mage) | Monkey King Bar | 80% pierce, nothing to cast, 1400 gold cheaper |
| healing | Alchemist, Necrophos, Huskar, Oracle or Lifestealer | Eye of Skadi, from minute 20 | in his build; attacks cut health restoration by 50%; high-rank players buy it more often against them (70% vs 61%), at the same ~27 min |
| illusions | Phantom Lancer, Naga Siren, Chaos Knight, Meepo, Terrorblade | Butterfly | 35% evasion: about a third of the illusions' attacks miss |
| lance | the same illusion heroes | Hydra's Breath | the Dragon Lance goes here, not into Pike: in Metamorphosis 30% of ranged attacks hit up to 3 more enemies, Miasma poisons them |
| lance | Slark, Phantom Assassin, Spirit Breaker | Hurricane Pike | pushes the jumper 425 away, 5 attacks from range with +100 attack speed |
| (generic) | Bristleback, Spectre, Huskar (after Skadi) | Silver Edge | the generic break counter, unchanged |

**Usual build** (all 325 won games, share and median minute): Power Treads 100%
(6) → Falcon Blade 84% (8) → Manta Style 100% (16) → Aghanim's Shard 83% (17) → Dragon Lance 92% (19) →
Eye of Skadi 70% (27) → Hurricane Pike 44% (27, not after Hydra's Breath) →
Butterfly 48% (29) → Black King Bar 37% (33) → Daedalus 28% (35). The all-ranks
OpenDota popularity it replaces had no Falcon Blade, Shard or Dragon Lance step.

**Skill build** (634 games): max Conjure Image → Metamorphosis → Reflection (62%,
won 56%; Conjure Image first in 560); first point Conjure Image (463),
Metamorphosis at level 2 (82%); Sunder at 6 (49%) or 7-9 (45%) wins the same
(53%/52%), so the level-6 ultimate tip stays. Talents: 10 Conjure Image
Cooldown (623 of 632), 15 Metamorphosis Cooldown (409 of 584), 20 Conjure Image
Duration (347 of 445), 25 Metamorphosis Duration (40 of 63). Against illusion
heroes the order is the same. Level 15 never names Sunder Minimum HP Swap. Level
20 names +10 All Attributes instead with 2+ enemy heroes whose area damage or
Hex clears illusions (`draft_analysis.ILLUSION_CLEARERS`): his players take it in
11% of games with none of them, 31% with one, 44% with two or more.

**Tempo:** with his own net worth over 12.0k at 20:00, 16.8k at 25:00 and 21.1k
at 30:00 (linear between, the same slope after), the counters wait and the next
item is the tempo build's, in the order of his farmed won games — Manta Style
(100% of them, ~15 min), Aghanim's Shard (78%, 16), Dragon Lance (93%, 18), Eye
of Skadi (62%, 25), Butterfly (50%, 25), Daedalus (25%, 31) — then the Aegis and
the throne. In 617 league games of patch 7.41 (OpenDota
Explorer) he wins 86-100% with 12.5k+ gold by 20:00, 94% with 17.5k+ by 25:00 and
85% with 22k+ by 30:00, against 52-56% at 10-12k by 20:00.

The same games back the counters: Monkey King Bar in 45% of games against
Phantom Assassin or Windranger (12% otherwise); Bloodthorn 12% (5%) when an
escape hero is there too, won 67% against 50%; against illusion heroes Butterfly
51% (38%), Hurricane Pike 18% (44%) and Maelstrom never. Dragon Lance is in 87% of
his games. Silver Edge against Bristleback, Spectre or Huskar: 42% (7%), won 70%
against 43%. Samples are small (25-100 games per lineup) and a
bought item also means a farmed hero: these are checks, not proof.

The illusion, Pike and tempo rules come from a player's review (2026-10-17),
checked against the items' Valve data. Butterfly and other enemy items are not
visible to a player's GSI, so no rule may depend on them.
