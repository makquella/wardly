"""
map_hints.py - the overlay's one-line map hint: timers and role tips.

A second channel next to the advice card: it never replaces advice, never
goes through the scheduler and never speaks over it (the overlay reads timers
marked "speak" only when the voice reads every advice).

1. Timers (data/meta/map_timers.json, checked against a patch): runes, wisdom
   shrines, lotuses, the Tormentor, neutral item tiers. Each event is shown from
   `lead_seconds` before it until `grace_seconds` after, and only to the
   positions it matters for (app/live_role.py).
2. Role tips: "no TP scroll" for any hero the carry advisor does not follow
   (it has its own); mid: the level-6 rotation window, the last-hit pace at
   5:00 and 8:00, no Bottle in the first minutes, and with level 6 the power
   rune reads "take it and go to a side lane"; offlane: the level-6 pressure
   window and a lost lane (two deaths, or level 4 at 6:00) → pull the big camp
   and survive for experience; supports: leave the last hits to the carry,
   stack a camp in given minutes, pull the small camp at :15 / :45 in the safe
   lane, "no observer ward on you" at most every 5 minutes, and 1500+ gold
   kept after 8:00 → spend it. A tip wins over a minor timer (runes, lotus:
   the stack window always comes before a power rune).

Texts are built in the request language here (like game_plan.py); the file's
events carry both languages.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from typing import Any

from app.config import DATA_DIR
from app.last_moments import RUNES_UK
from app.live_tools import POWER_RUNES

TIMERS_PATH = DATA_DIR / "meta" / "map_timers.json"

# Support tip: stack a camp in these minutes (pull at :53-:55).
STACK_MINUTES = (4, 7, 10, 13, 16)
STACK_FROM_SECOND = 38
STACK_UNTIL_SECOND = 53
# Support tip: no observer ward in the inventory.
WARD_FROM_CLOCK = 150
WARD_EVERY = 5 * 60
# After this many «No observer wards» reminders, twice the pause.
WARD_SLOW_AFTER = 3
WARD_SHOW = 20

WARD_ITEMS = {"item_ward_observer", "item_ward_dispenser"}
# Support tip: the same observer ward carried this long (nothing placed).
WARD_HELD = 2 * 60
WARD_HELD_EVERY = 3 * 60
# Support tip: an invisible enemy hero seen (enemy_heroes.py) and no Dust of
# Appearance or sentry ward carried.
INVIS_FROM = 6 * 60
INVIS_EVERY = 6 * 60
INVIS_SHOW = 20
DETECTION_ITEMS = {"item_dust", "item_ward_sentry", "item_ward_dispenser", "item_gem"}
# Where the ward goes: the lane's river until 10:00, then by the kill score
# (8+ kills apart, as the farm advice) or Roshan's pit while he can be up.
WARD_LANING_END = 10 * 60
WARD_SCORE_FROM = 12 * 60
WARD_SCORE_GAP = 8
# Support tip: no save item after this clock with this much gold.
SAVE_ITEMS = {
    "item_glimmer_cape",
    "item_force_staff",
    "item_hurricane_pike",
    "item_ghost",
    "item_ethereal_blade",
    "item_lotus_orb",
    "item_solar_crest",
    "item_pavise",
    "item_guardian_greaves",
}
SAVE_FROM = 12 * 60
# The past-lanes tip (lane_duel.lane_record_for): once per match, in this window.
LANE_RECORD_FROM, LANE_RECORD_UNTIL = 90, 8 * 60
LANE_RECORD_SHOW = 20
# «Missing» calls (enemy_lanes.py): shown this long, at most one per MISSING_GAP.
MISSING_SHOW = 15
MISSING_GAP = 45
SAVE_GOLD = 1200
SAVE_EVERY = 5 * 60
SAVE_SHOW = 20
# Any role without the carry advisor (which has its own TP advice): no TP scroll.
TP_EVERY = 4 * 60
TP_SHOW = 20
# Support tip: a support farming the lane like a core leaves its carry poor.
LAST_HITS_FROM = 3 * 60
LAST_HITS_UNTIL = 10 * 60
SUPPORT_LH_PER_MIN = 2.5
LAST_HITS_EVERY = 3 * 60
# Level 6 before this clock: the mid's rotation window, the offlaner's pressure.
POWER_SPIKE_LEVEL = 6
POWER_SPIKE_UNTIL = 12 * 60
POWER_SPIKE_SHOW = 25
# Mid: last hits at these clocks against a good pace (a core's 55 at 10:00).
MID_LAST_HIT_CHECKS = {5 * 60: 25, 8 * 60: 44}
MID_LAST_HIT_SHOW = 20
# Mid: no Bottle in these minutes (most mids live on it and the runes).
BOTTLE_FROM = 3 * 60 + 30
BOTTLE_UNTIL = 6 * 60
BOTTLE_SHOW = 20
BOTTLE_ITEMS = {"item_bottle"}
# Lane tips for cores (0.36): what players forget in the first ten minutes.
# Regen on the way to lane: none of these in the inventory by 1:30.
LANE_REGEN_ITEMS = {
    "item_tango",
    "item_tango_single",
    "item_flask",
    "item_faerie_fire",
    "item_enchanted_mango",
    "item_bottle",
}
LANE_REGEN_UNTIL = 90
LANE_REGEN_SHOW = 20
# HP half gone in lane with nothing to heal and gold for a Healing Salve.
LANE_HP_FROM, LANE_HP_UNTIL = 120, 10 * 60
LANE_HP_LIMIT = 50
LANE_HP_GOLD = 110
LANE_HP_EVERY, LANE_HP_SHOW = 180, 15
# A Magic Stick by mid-lane: the cheapest save of the game.
STICK_ITEMS = {"item_magic_stick", "item_magic_wand"}
STICK_FROM, STICK_UNTIL = 3 * 60, 8 * 60
STICK_GOLD = 200
STICK_SHOW = 20
# Denies at 4:00 for a carry or a mid who is last-hitting.
DENY_AT = 4 * 60
DENY_SHOW = 20
DENY_MIN = 3
# Behind the lane opponent's usual last hits (lane_duel.lane_pace_for): checked at
# each of its minutes, shown once for PACE_SHOW seconds when PACE_MARGIN+ short.
PACE_SHOW = 20
PACE_MARGIN = 3
# The enemy draft read (situational_items.draft_item): once per match for a core,
# in this window, for DRAFT_SHOW seconds.
DRAFT_FROM, DRAFT_UNTIL = 3 * 60, 10 * 60
DRAFT_SHOW = 20
# A hero plan's note: once per match, this long.
PLAN_NOTE_SHOW = 20
# Enemies seen together far from the player (enemy_group): GROUP_MIN heroes
# within GROUP_RADIUS of one another, GROUP_FAR or more from the player, from
# GROUP_FROM on; shown GROUP_SHOW seconds, at most once per GROUP_EVERY.
GROUP_MIN = 4
GROUP_RADIUS = 2500
GROUP_FAR = 4000
GROUP_FROM = 10 * 60
GROUP_SHOW = 15
GROUP_EVERY = 180
# A fight the player is not in (fight_summary.py): shown FIGHT_SHOW seconds, at
# most once per FIGHT_EVERY.
FIGHT_SHOW = 12
# A plan card (live_plan.py) stays this long from the snapshot it started.
PLAN_SHOW = 12
FIGHT_EVERY = 60
DENY_MIN_LAST_HITS = 8
# A power rune kept in the Bottle this long (clock seconds, alive) → use it.
BOTTLE_RUNE_HELD = 30
BOTTLE_RUNE_SHOW = 20
# Offlane: a lost lane — this many deaths, or below this level at 6:00.
HARD_LANE_FROM = 4 * 60
HARD_LANE_UNTIL = 9 * 60
HARD_LANE_DEATHS = 2
HARD_LANE_LEVEL_AT = 6 * 60
HARD_LANE_LEVEL = 5
HARD_LANE_SHOW = 25
# Safe-lane support: pull the small camp so the wave meets at the own tower.
PULL_FROM = 2 * 60
PULL_UNTIL = 8 * 60
PULL_WINDOWS = ((5, 15), (35, 45))  # (from second, pull at second)
PULL_EVERY = 2 * 60
PULL_SHOW = 10
# Cores: the hero's key item (OpenDota's most bought, with its typical finish
# time) — late by this much, or finished this much before the typical time.
KEY_ITEM_LATE = 2 * 60
KEY_ITEM_EARLY = 2 * 60
KEY_ITEM_SHOW = 25
# A role chosen in the settings that the lane read contradicts: said once, after
# the lane decision (3:00), for 20 s.
ROLE_CHECK_FROM = 3 * 60
ROLE_CHECK_SHOW = 20
ROLE_NAMES = {
    "en": {"carry": "carry", "mid": "mid", "offlane": "offlaner", "support": "support"},
    "uk": {"carry": "керрі", "mid": "мід", "offlane": "хардлайнер", "support": "саппорт"},
}
CORE_ROLES = {"carry", "mid", "offlane"}
# Support: gold kept instead of wards, dust, smoke and a save item.

TIPS = {
    "stack": {
        "en": ("Stack a camp", "Pull the camp at :53 so the next spawn stacks on top."),
        "uk": ("Застакайте табір", "Відведіть кріпів на :53 — згори з'явиться новий табір."),
    },
    "tp": {
        "en": ("No TP scroll", "Buy one now: without it you cannot join a fight or save a tower."),
        "uk": (
            "Немає сувою телепортації",
            "Купіть його зараз: без ТП не встигнути на бійку й до вежі.",
        ),
    },
    "last_hits": {
        "en": (
            "Leave the last hits to your carry",
            "A support's gold comes from runes, stacks and kills.",
        ),
        "uk": ("Залиште добивання керрі", "Золото саппорта — руни, стаки й убивства."),
    },
    "wards": {
        "en": ("No observer wards on you", "Take wards from the shop and light up the next fight."),
        "uk": ("Немає вардів", "Візьміть варди в крамниці й підсвітіть місце наступної бійки."),
    },
    "ward_bag": {
        "en": (
            "Place your observer ward",
            "A ward in the bag shows nothing: put it where the next fight or gank will come from.",
        ),
        "uk": (
            "Поставте вард",
            "Вард у сумці нічого не показує: поставте його там, звідки прийде бійка або ганк.",
        ),
    },
    "invis_dust": {
        "en": (
            "{enemy} goes invisible",
            "Carry Dust of Appearance or a sentry ward into fights: without them nobody can hit {enemy}.",
        ),
        "uk": (
            "{enemy} іде в невидимість",
            "Носіть у бійки Dust of Appearance або сентрі: без них {enemy} ніхто не вдарить.",
        ),
    },
    # Where to put it: by the phase of the game, the kill score and Roshan.
    "ward_bag_lane": {
        "en": (
            "Place your observer ward",
            "Put it by the river next to your lane: a gank shows up before it reaches you.",
        ),
        "uk": (
            "Поставте вард",
            "Поставте його біля річки поруч із вашою лінією: ганк буде видно заздалегідь.",
        ),
    },
    "ward_bag_behind": {
        "en": (
            "Place your observer ward",
            "Your team is {gap} kills behind: ward the entrances to your own jungle, "
            "where the enemy comes to catch your cores.",
        ),
        "uk": (
            "Поставте вард",
            "Команда відстає на {gap} вбивств: поставте його біля входу у свій ліс — там ворог ловить тих, хто фармить.",
        ),
    },
    "ward_bag_ahead": {
        "en": (
            "Place your observer ward",
            "Your team is {gap} kills ahead: ward the enemy jungle so your team can "
            "catch their cores and take towers safely.",
        ),
        "uk": (
            "Поставте вард",
            "Команда попереду на {gap} вбивств: поставте його в лісі ворога — так команда спіймає їхніх героїв, що фармлять, і безпечно знесе вежі.",
        ),
    },
    "ward_bag_roshan": {
        "en": (
            "Place your observer ward",
            "Roshan can be up now: put it by the Roshan pit so the enemy cannot take it unseen.",
        ),
        "uk": (
            "Поставте вард",
            "Рошан уже може з'явитися: поставте його біля лігва — ворог не забере його непомітно.",
        ),
    },
    "save_item": {
        "en": (
            "No save item yet",
            "Glimmer Cape or Force Staff saves a core in a fight: buy one of them next.",
        ),
        "uk": (
            "Немає рятівного предмета",
            "Glimmer Cape або Force Staff рятують кора в бійці: купіть один із них наступним.",
        ),
    },
    # The save item most bought on the hero (cached OpenDota build).
    "save_item_hero": {
        "en": (
            "No save item yet: {item}",
            "{item} is the save item most bought on this hero: {left} gold to go.",
        ),
        "uk": (
            "Немає рятівного предмета: {item}",
            "{item} найчастіше беруть на цьому герої, щоб рятувати союзників: лишилося {left} золота.",
        ),
    },
    "save_item_now": {
        "en": (
            "Buy {item} now",
            "{item} is the save item most bought on this hero, and you have the gold for it.",
        ),
        "uk": (
            "Купіть {item} зараз",
            "{item} найчастіше беруть на цьому герої, щоб рятувати союзників, і золота на нього вистачає.",
        ),
    },
    # The save item against the enemy lineup (situational_items.lineup_save_item).
    "save_item_now_lineup": {
        "en": (
            "Buy {item} now",
            "{item} fits against this enemy lineup, and you have the gold for it.",
        ),
        "uk": (
            "Купіть {item} зараз",
            "{item} найкращий проти цього складу ворога, і золота на нього вистачає.",
        ),
    },
    "save_item_magic": {
        "en": (
            "{item} against their magic",
            "{count} enemy heroes deal magic damage, and {item} saves an ally from it.",
        ),
        "uk": (
            "{item} проти магії",
            "Героїв ворога з магічною шкодою: {count}, а {item} рятує від неї союзника.",
        ),
    },
    "save_item_physical": {
        "en": (
            "{item} against their carries",
            "{enemy} and other right-click carries: {item} stops their attacks for a few seconds.",
        ),
        "uk": (
            "{item} проти їхніх керрі",
            "У ворога {enemy} та інші керрі з ударами з руки: {item} на кілька секунд рятує від їхніх атак.",
        ),
    },
    # The player's past lanes against the hero now in their lane (lane_duel.py).
    "lane_hard": {
        "en": (
            "Hard lane: {hero}",
            "You lost the lane to {hero} {lost} of {games} times: play for experience, "
            "take only the safe last hits and call your support early.",
        ),
        "uk": (
            "Важка лінія: {hero}",
            "Проти {hero} ви програли лінію {lost} з {games} разів: грайте від досвіду, добивайте лише безпечних кріпів і кличте саппорта заздалегідь.",
        ),
    },
    "lane_easy": {
        "en": (
            "Your lane: {hero}",
            "You won the lane against {hero} {won} of {games} times: press from the "
            "first minutes and take their last hits away.",
        ),
        "uk": (
            "Зручна лінія: {hero}",
            "Проти {hero} ви виграли лінію {won} з {games} разів: тисніть із перших хвилин і не давайте добивати.",
        ),
    },
    # An enemy gone from the minimap in the laning stage (enemy_lanes.py).
    "missing_mid": {
        "en": (
            "Enemy mid missing: {hero}",
            "{hero} has not been seen for {seconds} s and may be coming to your lane. "
            "Stay closer to your tower.",
        ),
        "uk": (
            "Не видно міда: {hero}",
            "{hero} не видно вже {seconds} с — може йти на вашу лінію. Тримайтеся ближче до своєї вежі.",
        ),
    },
    "missing_lane": {
        "en": (
            "Your lane opponent is missing: {hero}",
            "{hero} has not been seen for {seconds} s: maybe coming around through the "
            "trees or off to another lane. Don't push up too far.",
        ),
        "uk": (
            "Суперник зник з лінії: {hero}",
            "{hero} не видно вже {seconds} с — може обходити через ліс або йти на іншу лінію. Не заходьте далеко вперед.",
        ),
    },
    "mid_six": {
        "en": (
            "Level 6: look for a rotation",
            "Push the wave first, then check the side lanes with the next rune.",
        ),
        "uk": (
            "6-й рівень: час ротації",
            "Спершу запуште хвилю, потім із руною подивіться на бокові лінії.",
        ),
    },
    "mid_last_hits": {
        "en": (
            "{last_hits} last hits by {time}",
            "A good mid has {target}+: last-hit and deny under your tower, trade only with the wave on your side.",
        ),
        "uk": (
            "{last_hits} {last_hits_word} до {time}",
            "Добрий мід — {target}+: добивайте й денайте під своєю вежею, розміни — коли хвиля на вашому боці.",
        ),
    },
    "mid_bottle": {
        "en": (
            "No Bottle yet",
            "Most mids live on it: every rune refills it, and it keeps you in the lane without going to base.",
        ),
        "uk": (
            "Немає пляшки",
            "Більшість мідерів живе на ній: руна заповнює її, і не треба ходити на базу.",
        ),
    },
    "lane_regen": {
        "en": (
            "No regen for the lane",
            "Take Tango or a Healing Salve: the first trades cost HP, and walking to base costs the lane.",
        ),
        "uk": (
            "Немає регену на лінію",
            "Візьміть Tango або Healing Salve: перші розміни коштують HP, а похід на базу коштує лінії.",
        ),
    },
    "lane_hp": {
        "en": (
            "{hp}% HP and nothing to heal",
            "Buy a Healing Salve and send it with the courier: with half HP you cannot stand in for last hits.",
        ),
        "uk": (
            "{hp}% HP і нічим лікуватися",
            "Купіть Healing Salve і відправте кур'єром: з половиною HP лінію не відстояти.",
        ),
    },
    "lane_stick": {
        "en": (
            "No Magic Stick yet",
            "200 gold: it charges from enemy spells and heals you in one press — the cheapest save of the lane.",
        ),
        "uk": (
            "Ще немає Magic Stick",
            "200 золота: він заряджається від ворожих заклять і лікує одним натисканням — найдешевший порятунок на лінії.",
        ),
    },
    "lane_denies": {
        "en": (
            "{denies} denies by 4:00",
            "Finish your own creeps when they are low: a deny takes gold and half the experience from the enemy.",
        ),
        "uk": (
            "Денаїв до 4:00: {denies}",
            "Добивайте своїх кріпів із низьким HP: денай забирає у ворога золото й половину досвіду.",
        ),
    },
    # The enemy draft read: the counter item to plan for (situational_items.draft_item).
    "draft_evasion": {
        "en": (
            "Against their draft: {item}",
            "{enemy} dodges attacks: plan {item} after your first big item, most of your attacks go through.",
        ),
        "uk": (
            "Проти їхнього драфту: {item}",
            "{enemy} ухиляється від атак: заплануйте {item} після першого великого предмета, більшість ваших атак пробиватиме ухилення.",
        ),
    },
    # A fight elsewhere (fight_summary.py): the facts, the decision stays the player's.
    "fight": {
        "en": (
            "Fight {place}: {a} allies, {e} enemies",
            "{status}Whether to go is your call with the team.",
        ),
        "uk": (
            "Бійка {place}: союзників {a}, ворогів {e}",
            "{status}Іти чи ні — вирішуйте з командою.",
        ),
    },
    # The short-term plan (live_plan.py): started only when the best action
    # changes; the facts it rests on, the next step, and what is unknown.
    "plan_lane": {
        "en": (
            "+{lh} last {hits} from {start} to {end}",
            "{why}Stay by your tower for the last hits that reach it and ask a support to "
            "come. Leave the lane only for camps you know your hero clears at this level.",
        ),
        "uk": (
            "Добивань: +{lh} з {start} до {end}",
            "{why}Тримайтеся біля вежі й добивайте кріпів, що до неї доходять, і покличте "
            "саппорта. Ідіть з лінії лише до таборів, які ваш герой точно зачистить на цьому рівні.",
        ),
    },
    "plan_delivery": {
        "en": (
            "{item} is in your stash",
            "Have the courier bring it: until it is with you it is not a button you can press.",
        ),
        "uk": (
            "{item} у схованці",
            "Нехай кур'єр привезе: поки предмета немає з вами, його не натиснути.",
        ),
    },
    "plan_delivery_item": {
        "en": (
            "{item} is in your stash",
            "Have the courier bring it: in the stash it gives you nothing.",
        ),
        "uk": (
            "{item} у схованці",
            "Нехай кур'єр привезе: у схованці предмет нічого вам не дає.",
        ),
    },
    "plan_backpack": {
        "en": (
            "{item} is in your backpack",
            "Swap it into the main slots: in the backpack it gives nothing and cannot be pressed.",
        ),
        "uk": (
            "{item} у рюкзаку",
            "Перекладіть в основні слоти: у рюкзаку предмет нічого не дає і не натискається.",
        ),
    },
    "plan_fight_tower": {
        "en": (
            "You took part in {took} kills: their T{tier} {lane} is in reach",
            "{allies} with you and no enemy in sight: hit the tower now.",
        ),
        "uk": (
            "Ви взяли участь у {took} вбивствах: їхня T{tier} {lane} поруч",
            "{allies} з вами, ворогів не видно: бийте вежу зараз.",
        ),
    },
    "plan_fight_recover": {
        "en": (
            "Fight over, {hp}% HP",
            "{part}Recover before the next one: heal or walk back while no enemy is in sight.",
        ),
        "uk": (
            "Бійка скінчилась, HP {hp}%",
            "{part}Відновіться перед наступною: лікуйтеся чи відходьте, поки ворогів не видно.",
        ),
    },
    "plan_aegis_team": {
        "en": (
            "Aegis until {until}",
            "{allies} with you: take the next tower or objective while it lasts.",
        ),
        "uk": (
            "Аегіс до {until}",
            "{allies} з вами: беріть наступну вежу чи ціль, поки він діє.",
        ),
    },
    "plan_aegis_alone": {
        "en": (
            "Aegis until {until}",
            "Group with your team: alone it covers only one mistake.",
        ),
        "uk": (
            "Аегіс до {until}",
            "Збирайтеся з командою: самому він прощає лише одну помилку.",
        ),
    },
    # Enemies seen together far away (enemy_group): no one goes there alone.
    "enemy_group": {
        "en": (
            "{n} enemies together {place}",
            "Do not go there alone: farm or push the other side of the map, with your TP ready for your team.",
        ),
        "uk": (
            "Ворогів разом — {n}, {place}",
            "Туди один не йдіть: фарміть чи штовхайте іншу сторону мапи, а ТП тримайте для команди.",
        ),
    },
    # A hero plan's note (hero_items.plan_note): advice with no item, its own words.
    "plan_note": {
        "en": ("Against {enemy}", "{reason}."),
        "uk": ("Проти {enemy}", "{reason}."),
    },
    # A hero plan's rule (hero_items.py) brings its own reason, both languages.
    "draft_reason": {
        "en": ("Against their draft: {item}", "{reason}."),
        "uk": ("Проти їхнього драфту: {item}", "{reason}."),
    },
    "draft_illusions": {
        "en": (
            "Against their draft: {item}",
            "{enemy} fights with illusions: plan {item} early, it hits them all at once.",
        ),
        "uk": (
            "Проти їхнього драфту: {item}",
            "{enemy} б'ється ілюзіями: заплануйте {item} рано, він б'є їх усіх одразу.",
        ),
    },
    "draft_healing": {
        "en": (
            "Against their draft: {item}",
            "{enemy} heals a lot: plan {item}, it cuts the healing in fights.",
        ),
        "uk": (
            "Проти їхнього драфту: {item}",
            "{enemy} багато лікується: заплануйте {item}, він ріже лікування в бійках.",
        ),
    },
    "draft_magic": {
        "en": (
            "Against their draft: {item}",
            "{count} enemy heroes deal magic damage: plan {item} after your first big item.",
        ),
        "uk": (
            "Проти їхнього драфту: {item}",
            "Героїв ворога з магічною шкодою — {count}: заплануйте {item} після першого великого предмета.",
        ),
    },
    "draft_break": {
        "en": (
            "Against their draft: {item}",
            "{enemy} relies on {spell}: plan {item}, its break turns that off.",
        ),
        "uk": (
            "Проти їхнього драфту: {item}",
            "{enemy} тримається на {spell}: заплануйте {item}, він це вимикає.",
        ),
    },
    "lane_pace": {
        "en": (
            "Behind {hero}'s pace: {mine} last hits",
            "In your past lanes against {hero} they had about {theirs} last hits by {minute}:00. "
            "Take every creep you can reach safely and deny when they go for one.",
        ),
        "uk": (
            "Відстаєте від темпу {hero}: {mine} добивань",
            "У ваших минулих лініях проти {hero} суперник мав близько {theirs} добивань до {minute}:00. "
            "Добивайте кожного крипа, до якого безпечно дотягнетеся, і денайте, коли суперник іде добивати.",
        ),
    },
    "bottle_rune": {
        "en": (
            "{rune} rune in your Bottle",
            "Use it for a kill on a side lane: the Bottle holds one rune, and the next one comes soon.",
        ),
        "uk": (
            "Руна {rune_uk} у пляшці",
            "Використайте її для вбивства на боковій лінії: у пляшці вміщається одна руна, а наступна з'явиться скоро.",
        ),
    },
    "mid_rune": {
        "en": ("", "Take it and go straight to a side lane: the best moment to rotate."),
        "uk": ("", "Заберіть її й одразу йдіть на бокову лінію: найкращий момент для ротації."),
    },
    "mid_rune_full": {
        "en": (
            "",
            "Your Bottle still holds a {rune} rune: use it now, or the new rune will not fit in.",
        ),
        "uk": (
            "",
            "У пляшці ще лежить руна {rune_uk}: використайте її зараз, інакше нова туди не вміститься.",
        ),
    },
    "mid_rune_bottle": {
        "en": ("", "Bottle it if you do not need it now: keep it for a kill after the next wave."),
        "uk": (
            "",
            "Якщо зараз не потрібна — покладіть її в пляшку й приберегіть для вбивства після наступної хвилі.",
        ),
    },
    "offlane_hard_lane": {
        "en": (
            "A hard lane",
            "Stop feeding under their tower: pull the big camp into your wave and take the experience safely.",
        ),
        "uk": (
            "Важка лінія",
            "Не помирайте під їхньою вежею: підтягніть великий табір у свою хвилю й беріть досвід без ризику.",
        ),
    },
    "pull": {
        "en": (
            "Pull at {at_label}",
            "Pull the small camp into your wave so it meets at your tower.",
        ),
        "uk": (
            "Пул о {at_label}",
            "Відведіть малий табір у свою хвилю: лінія стане біля вашої вежі.",
        ),
    },
    "item_late": {
        "en": (
            "{item} is late",
            "Most players finish it by {time}. Farm camps between waves and skip fights until you have it.",
        ),
        "uk": (
            "{item} запізнюється",
            "Зазвичай його збирають до {time}. Фарміть табори між хвилями й не лізьте в бійки без нього.",
        ),
    },
    "role_mismatch": {
        "en": (
            "Role in the settings: {setting}",
            "You play as {seen}, so some tips miss. Set “Your role” to Auto in Wardly.",
        ),
        "uk": (
            "Роль у налаштуваннях: {setting}",
            "А граєте ви як {seen}, тому частина підказок не до речі. Поставте «Ваша роль» → «Авто» у Wardly.",
        ),
    },
    "item_early": {
        "en": (
            "{item} ahead of time",
            "Most players have it by {time}: this is your window — push and look for fights.",
        ),
        "uk": (
            "{item} раніше, ніж зазвичай",
            "Зазвичай його збирають до {time}: зараз ваше вікно — тисніть і шукайте бійки.",
        ),
    },
    "offlane_six": {
        "en": (
            "Level 6: pressure the lane",
            "With your support, go for the enemy carry or their tower while the wave is close.",
        ),
        "uk": (
            "6-й рівень: тисніть лінію",
            "Разом із саппортом ідіть на ворожого керрі або вежу, поки хвиля поруч.",
        ),
    },
}


# The overlay's timer strip: the next events for the position, at most this many,
# within this many seconds (Roshan and the Aegis at any distance).
STRIP_SIZE = 3
STRIP_AHEAD = 3 * 60
STRIP_LABELS = {
    "water_rune": ("Руна води", "Water rune"),
    "power_rune": ("Руна", "Rune"),
    "bounty_rune": ("Багатство", "Bounty"),
    "wisdom_shrine": ("Мудрість", "Wisdom"),
    "lotus": ("Лотос", "Lotus"),
    "tormentor": ("Торментор", "Tormentor"),
    "neutral_tier_2": ("Нейтралки", "Neutrals"),
    "neutral_tier_3": ("Нейтралки", "Neutrals"),
    "neutral_tier_4": ("Нейтралки", "Neutrals"),
    "neutral_tier_5": ("Нейтралки", "Neutrals"),
    "stack": ("Стак", "Stack"),
    "roshan": ("Рошан", "Roshan"),
    "roshan_maybe": ("Рошан?", "Roshan?"),
    "aegis": ("Аегіс", "Aegis"),
    "enemy_aegis": ("Аегіс ворогів", "Enemy Aegis"),
}


def enemy_group(
    units: list[dict[str, Any]] | None, x: Any, y: Any, team: Any
) -> dict[str, Any] | None:
    """The largest group of visible enemy heroes (enemy_heroes.visible_enemy_units,
    absolute coordinates) when it has GROUP_MIN+ heroes and is GROUP_FAR or more
    from the player at (x, y): {count, heroes, zone, side}; None otherwise."""
    from app.map_analysis import map_side, zone

    if (
        not isinstance(x, (int, float))
        or not isinstance(y, (int, float))
        or team
        not in (
            "radiant",
            "dire",
        )
    ):
        return None
    points = [
        (u["hero"], float(u["x"]), float(u["y"]))
        for u in units or []
        if isinstance(u, dict)
        and isinstance(u.get("x"), (int, float))
        and isinstance(u.get("y"), (int, float))
    ]
    best: list[tuple[str, float, float]] = []
    for _, px, py in points:
        near = [p for p in points if math.hypot(p[1] - px, p[2] - py) <= GROUP_RADIUS]
        if len(near) > len(best):
            best = near
    if len(best) < GROUP_MIN:
        return None
    cx, cy = sum(p[1] for p in best) / len(best), sum(p[2] for p in best) / len(best)
    if math.hypot(cx - x, cy - y) < GROUP_FAR:
        return None
    return {
        "count": len(best),
        "heroes": [p[0] for p in best],
        "zone": zone(cx, cy),
        "side": map_side(cx, cy, team == "radiant"),
    }


def group_place(group: dict[str, Any], lang: str) -> str:
    """Where a group is, as in the death screen: «на нижній лінії на своїй половині»."""
    from app.analysis_texts import PLACE_SIDES, PLACE_ZONES

    zone_id, side = str(group.get("zone")), str(group.get("side"))
    sides = PLACE_SIDES[lang]
    if lang == "uk":
        zones = PLACE_ZONES["uk"]["in"]
        return f"{zones.get(zone_id, '')} {sides.get(side, '')}".strip()
    names = PLACE_ZONES["en"]["name"]
    return f"in the {names.get(zone_id, 'map')} {sides.get(side, '')}".strip()


FIGHT_WORDS = {
    "uk": {
        "own": "біля вашої T{tier} {lane}",
        "enemy": "біля їхньої T{tier} {lane}",
        "tp_ready": "ТП — готово",
        "tp_in": "ТП — через {s} с",
        "no_tp": "ТП немає",
        "ready": "{name} — готово",
        "in": "{name} — через {s} с",
        "not_ready": "{name} — не готово",
    },
    "en": {
        "own": "at your T{tier} {lane}",
        "enemy": "at their T{tier} {lane}",
        "tp_ready": "TP ready",
        "tp_in": "TP in {s} s",
        "no_tp": "no TP",
        "ready": "{name} ready",
        "in": "{name} in {s} s",
        "not_ready": "{name} not ready",
    },
}


def fight_params(fight: dict[str, Any], lang: str) -> dict[str, Any]:
    """{place, a, e, status} for the fight card in `lang`."""
    from app.analysis_texts import PLACE_ZONES
    from app.map_analysis import map_side, zone

    words = FIGHT_WORDS[lang]
    tower = fight.get("tower")
    team = fight.get("team")
    if isinstance(tower, dict) and team in ("radiant", "dire"):
        lane = str(tower.get("lane") or "base")
        lane_text = (
            PLACE_ZONES["uk"]["in"].get(lane, "")
            if lang == "uk"
            else f"in the {PLACE_ZONES['en']['name'].get(lane, lane)}"
        )
        side = "own" if tower.get("team") == team else "enemy"
        place = words[side].format(tier=tower.get("tier"), lane=lane_text)
    else:
        group = {
            "zone": zone(fight["x"], fight["y"]),
            "side": map_side(fight["x"], fight["y"], team == "radiant"),
        }
        place = group_place(group, lang)
    parts: list[str] = []
    cooldown = fight.get("tp_cooldown")
    if fight.get("has_tp") is False:
        parts.append(words["no_tp"])
    elif isinstance(cooldown, int):
        parts.append(words["tp_ready"] if cooldown == 0 else words["tp_in"].format(s=cooldown))
    for ability in fight.get("abilities") or []:
        if ability.get("ready"):
            parts.append(words["ready"].format(name=ability["name"]))
        elif ability.get("cooldown"):
            parts.append(words["in"].format(name=ability["name"], s=ability["cooldown"]))
        else:
            parts.append(words["not_ready"].format(name=ability["name"]))
    status = ", ".join(parts)
    if status:
        status = status[0].upper() + status[1:] + ". "
    return {
        "place": place,
        "a": len(fight.get("allies") or []),
        "e": len(fight.get("enemies") or []),
        "status": status,
    }


def _allies_text(count: int, lang: str) -> str:
    if lang == "uk":
        return f"{count} {_ru_plural(count, 'союзник', 'союзники', 'союзників')}"
    return f"{count} {'ally' if count == 1 else 'allies'}"


def plan_params(plan: dict[str, Any], lang: str) -> tuple[str, dict[str, Any]] | None:
    """(TIPS key, params) of a plan card in `lang`; None for a plan without one."""
    from app.analysis_texts import PLACE_ZONES

    basis = plan.get("basis") or {}
    goal = plan.get("goal")
    if goal == "lane_recover":
        facts = []
        if basis.get("hp_min") is not None and basis["hp_min"] <= 50:
            facts.append(
                f"HP впало до {basis['hp_min']}%"
                if lang == "uk"
                else f"HP down to {basis['hp_min']}%"
            )
        if basis.get("enemies", 0) >= 2:
            facts.append(
                f"ворогів поруч: {basis['enemies']}"
                if lang == "uk"
                else f"{basis['enemies']} enemies around you"
            )
        why = (", ".join(facts) + ". ") if facts else ""
        why = why[:1].upper() + why[1:]
        lh = int(basis.get("last_hits") or 0)
        return "plan_lane", {
            "lh": lh,
            "hits": "hit" if lh == 1 else "hits",
            "start": basis.get("from"),
            "end": basis.get("to"),
            "why": why,
        }
    if goal == "deliver_item":
        label = basis.get("label_uk" if lang == "uk" else "label") or basis.get("item")
        if plan.get("next") == "to_main_slots":
            return "plan_backpack", {"item": label}
        # A save presses; any other item (a passive, stats) just does nothing there.
        return ("plan_delivery" if basis.get("save", True) else "plan_delivery_item"), {
            "item": label
        }
    if goal == "after_fight":
        took = int(basis.get("took_part") or 0)
        if basis.get("next") == "tower" and isinstance(basis.get("tower"), dict):
            lane = str(basis["tower"].get("lane") or "base")
            lane_text = (
                PLACE_ZONES["uk"]["in"].get(lane, "")
                if lang == "uk"
                else f"in the {PLACE_ZONES['en']['name'].get(lane, lane)}"
            )
            return "plan_fight_tower", {
                "took": took,
                "tier": basis["tower"].get("tier"),
                "lane": lane_text,
                "allies": _allies_text(int(basis.get("allies") or 0), lang).capitalize(),
            }
        if basis.get("next") == "recover":
            part = ""
            if took:
                part = (
                    f"Ви взяли участь у {took} вбивствах. "
                    if lang == "uk"
                    else f"You took part in {took} {'kill' if took == 1 else 'kills'}. "
                )
            return "plan_fight_recover", {"hp": basis.get("hp"), "part": part}
        return None
    if goal == "aegis_window":
        allies = int(basis.get("allies") or 0)
        if allies:
            return "plan_aegis_team", {
                "until": basis.get("until"),
                "allies": _allies_text(allies, lang).capitalize(),
            }
        return "plan_aegis_alone", {"until": basis.get("until")}
    return None


def strip_item(kind: str, at: int, clock: int, lang: str, **extra: Any) -> dict[str, Any]:
    uk, en = STRIP_LABELS[kind]
    return {
        "id": f"{kind}@{at}",
        "kind": kind,
        "label": uk if lang == "uk" else en,
        "at": at,
        "at_label": clock_label(at),
        "in_seconds": at - clock,
        **extra,
    }


def timer_strip(
    clock: int | None,
    role: str | None,
    lang: str,
    objectives: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """The next events for this position (one per kind, soonest first) and the
    Roshan / Aegis timers (`objectives`, roshan_timer.RoshanTimer.strip)."""
    if clock is None or clock < 0:
        return []
    items: list[dict[str, Any]] = []
    for event in timers().get("events") or []:
        until = (event.get("roles") or {}).get(role or "")
        if until is None:
            continue
        upcoming = [at for at in _times(event, int(until)) if clock <= at <= clock + STRIP_AHEAD]
        if upcoming and event["id"] in STRIP_LABELS:
            items.append(strip_item(event["id"], upcoming[0], clock, lang))
    if role == "support":
        minute, second = divmod(clock, 60)
        stacks = [
            m * 60 + STACK_UNTIL_SECOND
            for m in STACK_MINUTES
            if clock <= m * 60 + STACK_UNTIL_SECOND <= clock + STRIP_AHEAD
        ]
        if stacks:
            items.append(strip_item("stack", stacks[0], clock, lang))
    # Neutral item tiers share a label: only the next one.
    seen: set[str] = set()
    unique = []
    for item in sorted(items, key=lambda row: row["in_seconds"]):
        if item["label"] in seen:
            continue
        seen.add(item["label"])
        unique.append(item)
    fixed = [dict(item) for item in objectives or []]
    return (fixed + unique)[:STRIP_SIZE]


@lru_cache(maxsize=1)
def timers() -> dict[str, Any]:
    try:
        return json.loads(TIMERS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"events": []}


def item_names(items: Any) -> list[str] | None:
    """Item names in the inventory, backpack and stash of a raw GSI items block
    (None without one; the TP and neutral slots are left out)."""
    if not isinstance(items, dict) or not items:
        return None
    names = []
    for slot, item in items.items():
        name = item.get("name") if isinstance(item, dict) else item
        if str(slot).startswith(("slot", "stash")) and isinstance(name, str) and name != "empty":
            names.append(name)
    return names


def _observers(item: Any) -> int:
    """Observer wards in one inventory item: its `charges` (the combined dispenser
    counts its observers there, sentries in `secondary_charges`, so 0 is a real
    zero); a ward without a usable count is one."""
    name = item.get("name") if isinstance(item, dict) else item
    if str(name or "") not in WARD_ITEMS:
        return 0
    charges = item.get("charges") if isinstance(item, dict) else None
    valid = isinstance(charges, int) and not isinstance(charges, bool)
    return charges if valid and 0 <= charges < 100 else 1


def observer_charges(items: Any) -> int | None:
    """Observer wards carried in the inventory; None without an items block."""
    if not isinstance(items, dict) or not items:
        return None
    return sum(_observers(item) for slot, item in items.items() if str(slot).startswith("slot"))


def has_observer_ward(items: Any) -> bool | None:
    """From a raw GSI items block; None without one (stash and neutral slots skipped)."""
    count = observer_charges(items)
    return None if count is None else count > 0


def _times(event: dict[str, Any], until: int) -> list[int]:
    if "times" in event:
        return [int(t) for t in event["times"] if int(t) <= until]
    first, every = int(event.get("first", 0)), int(event.get("every", 0))
    if every <= 0:
        return [first] if first <= until else []
    return list(range(first, until + 1, every))


def clock_label(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def next_timer(clock: int, role: str | None, lang: str) -> dict[str, Any] | None:
    """The event about to happen (or just happened) for this position."""
    data = timers()
    lead = int(data.get("lead_seconds", 20))
    grace = int(data.get("grace_seconds", 5))
    # The soonest event; at the same second a major one (Tormentor) wins.
    candidates = [
        (at, bool(event.get("minor")), index, event)
        for index, event in enumerate(data.get("events") or [])
        if (until := (event.get("roles") or {}).get(role or "")) is not None
        for at in _times(event, int(until))
        if at - lead <= clock <= at + grace
    ]
    if not candidates:
        return None
    at, _minor, _index, event = min(candidates, key=lambda row: row[:3])
    uk = lang == "uk"
    return {
        "kind": "timer",
        "id": f"{event['id']}@{at}",
        "at": at,
        "at_label": clock_label(at),
        "in_seconds": at - clock,
        "title": event["uk" if uk else "en"],
        "hint": event.get("hint_uk" if uk else "hint_en") or "",
        "speak": bool(event.get("speak")),
        # Spoken in English when Windows has no Ukrainian voice (overlay/voice.js).
        "title_en": event["en"],
        "minor": bool(event.get("minor")),
        "patch": data.get("patch"),
    }


class RoleTips:
    """Per-match memory of the tips shown (reset with MatchMemory)."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._shown: dict[str, int] = {}
        self._shown_record: dict[str, Any] = {}
        self._shown_draft: dict[str, Any] = {}
        self._shown_group: dict[str, dict[str, Any]] = {}
        self._shown_fight: dict[str, dict[str, Any]] = {}
        # (observer wards carried, the clock since when none was placed).
        self._ward_held: tuple[int, int] | None = None
        # The clock of the last observer ward placed (the carried count went down).
        self._ward_placed: int | None = None
        # How many «No observer wards» reminders this match has shown.
        self._ward_nags = 0
        # Level 6 counts as reached only after a level below 6 was seen: a
        # backend started mid-game at level 8 must not call it a new spike.
        self._armed = False
        # (power rune in the Bottle, the clock it was first seen there).
        self._bottled: tuple[str, int] | None = None

    def observe_level(self, level: int | None) -> None:
        """Every hint request (also while a timer shows): arms the level-6 tip."""
        if level is not None and level < POWER_SPIKE_LEVEL:
            self._armed = True

    def observe_bottle(self, rune: str | None, clock: int) -> None:
        """Every hint request: since when the power rune in the Bottle is there."""
        if rune not in POWER_RUNES:
            self._bottled = None
        elif self._bottled is None or self._bottled[0] != rune or clock < self._bottled[1]:
            self._bottled = (rune, clock)

    def _bottle_rune(self, clock: int, lang: str) -> dict[str, Any] | None:
        """Once per bottled rune: a power rune kept BOTTLE_RUNE_HELD seconds."""
        if self._bottled is None:
            return None
        rune, since = self._bottled
        if clock - since < BOTTLE_RUNE_HELD:
            return None
        key = f"bottle_rune@{since}"
        start = self._once(key, clock, BOTTLE_RUNE_SHOW)
        if start is None:
            return None
        return _tip("bottle_rune", key, lang, rune=rune, rune_uk=RUNES_UK.get(rune, rune))

    def _every(self, key: str, clock: int, every: int, show: int) -> int | None:
        """Shown for `show` seconds, then again `every` seconds later: the start."""
        shown = self._shown.get(key)
        if shown is None or clock - shown >= every or clock < shown:
            self._shown[key] = shown = clock
        return shown if clock - shown <= show else None

    def _lane_record(
        self, clock: int, lang: str, record: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """The past record against the lane opponent, once per match for
        LANE_RECORD_SHOW seconds from the first second it is known."""
        if not (LANE_RECORD_FROM <= clock <= LANE_RECORD_UNTIL):
            return None
        if not record or record.get("kind") not in ("hard", "easy"):
            return None
        key = "lane_record"
        if key not in self._shown:
            self._shown[key] = clock
            self._shown_record = dict(record)
        if clock - self._shown[key] > LANE_RECORD_SHOW:
            return None
        shown = self._shown_record
        return _tip(
            f"lane_{shown['kind']}",
            f"lane_record@{self._shown[key]}",
            lang,
            hero=shown["hero"],
            won=shown["won"],
            lost=shown["lost"],
            games=shown["games"],
        )

    def fight(self, clock: int, lang: str, fight: dict[str, Any] | None) -> dict[str, Any] | None:
        """«Fight at your T2: 3 allies, 2 enemies» (fight_summary.py): FIGHT_SHOW
        seconds, at most once per FIGHT_EVERY; the words stay while it is up."""
        start = self._shown.get("fight")
        if start is not None and 0 <= clock - start <= FIGHT_SHOW:
            return _tip("fight", f"fight@{start}", lang, **self._shown_fight[lang])
        if not fight or (start is not None and 0 <= clock - start < FIGHT_EVERY):
            return None
        self._shown["fight"] = clock
        self._shown_fight = {key: fight_params(fight, key) for key in ("en", "uk")}
        return _tip("fight", f"fight@{clock}", lang, **self._shown_fight[lang])

    def plan(self, clock: int, lang: str, plan: dict[str, Any] | None) -> dict[str, Any] | None:
        """The card of a short-term plan (live_plan.py) for PLAN_SHOW seconds
        from its start; one card per plan."""
        if not plan or not 0 <= clock - int(plan.get("since", -(10**6))) <= PLAN_SHOW:
            return None
        rendered = plan_params(plan, lang)
        if rendered is None:
            return None
        key, params = rendered
        return _tip(key, f"plan_{plan['goal']}@{plan['since']}", lang, **params)

    def enemy_group(
        self, clock: int, lang: str, group: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """«N enemies together …» (enemy_group): GROUP_SHOW seconds, at most
        once per GROUP_EVERY; the card already up stays while it lasts."""
        start = self._shown.get("enemy_group")
        if start is not None and 0 <= clock - start <= GROUP_SHOW:
            shown = self._shown_group
            return _tip("enemy_group", f"enemy_group@{start}", lang, **shown[lang])
        if not group or clock < GROUP_FROM:
            return None
        if start is not None and 0 <= clock - start < GROUP_EVERY:
            return None
        self._shown["enemy_group"] = clock
        self._shown_group = {
            lang_key: {"n": group["count"], "place": group_place(group, lang_key)}
            for lang_key in ("en", "uk")
        }
        return _tip("enemy_group", f"enemy_group@{clock}", lang, **self._shown_group[lang])

    def missing(
        self, clock: int, lang: str, missing: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """The «missing» call for one disappearance of an enemy: shown for
        MISSING_SHOW seconds (with the seconds of its first second), at most
        one call per MISSING_GAP; nothing once the enemy is seen again."""
        if not missing or missing.get("kind") not in ("mid", "lane"):
            return None
        key = f"missing:{missing['hero']}@{missing['since']}"
        if key not in self._shown:
            last = self._shown.get("missing:last")
            if isinstance(last, int) and clock - last < MISSING_GAP:
                return None
            self._shown[key] = clock
            self._shown["missing:last"] = clock
            self._shown[f"{key}:seconds"] = int(missing["seconds"])
        start = self._shown[key]
        if not 0 <= clock - start <= MISSING_SHOW:
            return None
        tip = _tip(
            f"missing_{missing['kind']}",
            key,
            lang,
            hero=missing["hero"],
            seconds=self._shown[f"{key}:seconds"],
        )
        tip["speak"] = True
        tip["title_en"] = TIPS[f"missing_{missing['kind']}"]["en"][0].format(hero=missing["hero"])
        return tip

    def tip(
        self,
        clock: int,
        role: str | None,
        *,
        alive: bool,
        has_ward: bool | None,
        lang: str,
        tp_missing: bool = False,
        carry_advisor: bool = False,
        last_hits: int | None = None,
        level: int | None = None,
        deaths: int | None = None,
        gold: int | None = None,
        lane: str | None = None,
        items: list[str] | None = None,
        key_item: dict[str, Any] | None = None,
        ward_charges: int | None = None,
        save_item: dict[str, Any] | None = None,
        score_gap: int | None = None,
        roshan_open: bool = False,
        enemies: list[str] | None = None,
        denies: int | None = None,
        hp: int | None = None,
        regen: list[str] | None = None,
        lane_record: dict[str, Any] | None = None,
        draft_item: dict[str, Any] | None = None,
        plan_note: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        held_for = self._observe_wards(ward_charges, clock)
        if not alive or role is None:
            return None
        if tp_missing and not carry_advisor:
            start = self._every("tp", clock, TP_EVERY, TP_SHOW)
            if start is not None:
                return _tip("tp", f"tp@{start}", lang)
        if role in ("mid", "offlane") and level is not None:
            key = f"{role}_six"
            if level >= POWER_SPIKE_LEVEL and clock <= POWER_SPIKE_UNTIL and self._armed:
                # Once per match, from the moment the level is reached.
                start = self._shown.setdefault(key, clock)
                if 0 <= clock - start <= POWER_SPIKE_SHOW:
                    return _tip(key, f"{key}@{start}", lang)
        bottled = self._bottle_rune(clock, lang)
        if bottled is not None:
            return bottled
        if role in CORE_ROLES:
            record = self._lane_record(clock, lang, lane_record)
            if record is not None:
                return record
            lane = self._lane(clock, role, lang, items, gold, last_hits, denies, hp, regen)
            if lane is not None:
                return lane
            if draft_item is not None:
                planned = self._draft_item(clock, lang, draft_item)
                if planned is not None:
                    return planned
            if plan_note is not None:
                noted = self._plan_note(clock, lang, plan_note)
                if noted is not None:
                    return noted
            pace = (lane_record or {}).get("pace")
            if role in ("carry", "mid") and pace is not None:
                behind = self._lane_pace(clock, lang, pace, last_hits)
                if behind is not None:
                    return behind
        if role in CORE_ROLES and key_item and items is not None:
            timing = self._key_item(clock, lang, key_item, items)
            if timing is not None:
                return timing
        if role == "mid":
            return self._mid(clock, lang, last_hits, items)
        if role == "offlane":
            return self._offlane(clock, lang, deaths, level)
        if role != "support":
            return None
        if (
            last_hits is not None
            and LAST_HITS_FROM <= clock <= LAST_HITS_UNTIL
            and last_hits / (clock / 60) >= SUPPORT_LH_PER_MIN
        ):
            start = self._every("last_hits", clock, LAST_HITS_EVERY, TP_SHOW)
            if start is not None:
                return _tip("last_hits", f"last_hits@{start}", lang)
        minute, second = divmod(clock, 60)
        if minute in STACK_MINUTES and STACK_FROM_SECOND <= second <= STACK_UNTIL_SECOND:
            at = minute * 60 + STACK_UNTIL_SECOND
            return _tip("stack", f"stack@{minute}", lang, at=at, clock=clock)
        if lane == "safe" and PULL_FROM <= clock <= PULL_UNTIL:
            for window_from, pull_at in PULL_WINDOWS:
                if window_from <= second <= pull_at:
                    start = self._every("pull", clock, PULL_EVERY, PULL_SHOW)
                    if start is not None:
                        at = minute * 60 + pull_at
                        label = clock_label(at)
                        return _tip("pull", f"pull@{at}", lang, at=at, clock=clock, at_label=label)
        invisible = _invisible_enemy(enemies)
        if (
            invisible
            and items is not None
            and clock >= INVIS_FROM
            and not DETECTION_ITEMS & set(items)
        ):
            start = self._every("invis_dust", clock, INVIS_EVERY, INVIS_SHOW)
            if start is not None:
                return _tip("invis_dust", f"invis_dust@{start}", lang, enemy=invisible)
        placed = self._ward_placed
        just_warded = placed is not None and 0 <= clock - placed < WARD_EVERY
        if has_ward is False and clock >= WARD_FROM_CLOCK and not just_warded:
            every = WARD_EVERY * (2 if self._ward_nags >= WARD_SLOW_AFTER else 1)
            start = self._every("wards", clock, every, WARD_SHOW)
            if start is not None:
                if start == clock:
                    self._ward_nags += 1
                return _tip("wards", f"wards@{start}", lang)
        if held_for is not None and held_for >= WARD_HELD and clock >= WARD_FROM_CLOCK:
            start = self._every("ward_bag", clock, WARD_HELD_EVERY, WARD_SHOW)
            if start is not None:
                return _ward_bag_tip(f"ward_bag@{start}", lang, clock, score_gap, roshan_open)
        if (
            items is not None
            and clock >= SAVE_FROM
            and not SAVE_ITEMS & set(items)
            and gold is not None
            and gold >= SAVE_GOLD
        ):
            start = self._every("save_item", clock, SAVE_EVERY, SAVE_SHOW)
            if start is not None:
                return _save_item_tip(f"save_item@{start}", lang, save_item, gold)
        # Unspent gold is app/gold_tips.py now: any role, map timers on or off.
        return None

    def _lane(
        self,
        clock: int,
        role: str,
        lang: str,
        items: list[str] | None,
        gold: int | None,
        last_hits: int | None,
        denies: int | None,
        hp: int | None,
        regen: list[str] | None,
    ) -> dict[str, Any] | None:
        """A core's lane tips in the first ten minutes: regen on the way, HP half
        gone with nothing to heal, a Magic Stick, denies at 4:00."""
        owned = set(items) if items is not None else None
        if owned is not None and clock <= LANE_REGEN_UNTIL and not LANE_REGEN_ITEMS & owned:
            start = self._once("lane_regen", clock, LANE_REGEN_SHOW)
            if start is not None:
                return _tip("lane_regen", f"lane_regen@{start}", lang)
        if (
            LANE_HP_FROM <= clock <= LANE_HP_UNTIL
            and hp is not None
            and hp <= LANE_HP_LIMIT
            and regen == []
            and gold is not None
            and gold >= LANE_HP_GOLD
        ):
            start = self._every("lane_hp", clock, LANE_HP_EVERY, LANE_HP_SHOW)
            if start is not None:
                shown = self._shown.setdefault(f"lane_hp_value@{start}", hp)
                return _tip("lane_hp", f"lane_hp@{start}", lang, hp=shown)
        if (
            owned is not None
            and STICK_FROM <= clock <= STICK_UNTIL
            and not STICK_ITEMS & owned
            and gold is not None
            and gold >= STICK_GOLD
        ):
            start = self._once("lane_stick", clock, STICK_SHOW)
            if start is not None:
                return _tip("lane_stick", f"lane_stick@{start}", lang)
        if (
            role in ("carry", "mid")
            and DENY_AT <= clock <= DENY_AT + DENY_SHOW
            and denies is not None
            and denies < DENY_MIN
            and (last_hits or 0) >= DENY_MIN_LAST_HITS
        ):
            shown = self._shown.setdefault("lane_denies@value", denies)
            return _tip("lane_denies", f"lane_denies@{DENY_AT}", lang, denies=shown)
        return None

    def _draft_item(self, clock: int, lang: str, item: dict[str, Any]) -> dict[str, Any] | None:
        """Once per match in the draft window: the item first named against the
        enemy lineup, kept while the card is up."""
        if "draft_item" not in self._shown:
            known = isinstance(item.get("reason"), dict) or f"draft_{item.get('why')}" in TIPS
            if not DRAFT_FROM <= clock <= DRAFT_UNTIL or not known:
                return None
            self._shown_draft = dict(item)
        start = self._once("draft_item", clock, DRAFT_SHOW)
        if start is None:
            return None
        shown = self._shown_draft
        reason = shown.get("reason")
        if isinstance(reason, dict):
            tip = _tip(
                "draft_reason",
                f"draft_item@{start}",
                lang,
                item=shown["name"],
                reason=reason.get(lang) or reason["en"],
            )
            tip["items"] = [{"key": shown["key"], "name": shown["name"]}]
            return tip
        tip = _tip(
            f"draft_{shown['why']}",
            f"draft_item@{start}",
            lang,
            item=shown["name"],
            enemy=shown.get("enemy") or "",
            spell=shown.get("spell") or "",
            count=shown.get("count") or 0,
        )
        tip["items"] = [{"key": shown["key"], "name": shown["name"]}]
        return tip

    def _plan_note(self, clock: int, lang: str, note: dict[str, Any]) -> dict[str, Any] | None:
        """Once per match per note: a hero plan's advice with no item."""
        key = f"note_{note['id']}"
        start = self._once(key, clock, PLAN_NOTE_SHOW)
        if start is None:
            return None
        reason = note["reason"]
        return _tip(
            "plan_note",
            f"{key}@{start}",
            lang,
            enemy=note["enemy"],
            reason=reason.get(lang) or reason["en"],
        )

    def _lane_pace(
        self, clock: int, lang: str, pace: dict[str, Any], last_hits: int | None
    ) -> dict[str, Any] | None:
        """At each pace minute: last hits PACE_MARGIN+ under the lane opponent's
        average in the player's past lanes against them; once per minute."""
        if last_hits is None:
            return None
        for minute, theirs in pace["lh"].items():
            at = minute * 60
            if not at <= clock <= at + PACE_SHOW:
                continue
            key = f"lane_pace@{at}"
            mine = self._shown.setdefault(f"{key}:mine", last_hits)
            if theirs - mine < PACE_MARGIN:
                return None
            return _tip(
                "lane_pace", key, lang, hero=pace["hero"], mine=mine, theirs=theirs, minute=minute
            )
        return None

    def _observe_wards(self, charges: int | None, clock: int) -> int | None:
        """Seconds the carried observer wards went without one being placed; None
        without a ward. Buying more keeps the time, placing one restarts it."""
        held = self._ward_held
        if held is not None and clock >= held[1] and (charges or 0) < held[0]:
            self._ward_placed = clock
        if not charges:
            self._ward_held = None
            return None
        if held is None or charges < held[0] or clock < held[1]:
            self._ward_held = (charges, clock)
        elif charges > held[0]:
            self._ward_held = (charges, held[1])
        return clock - self._ward_held[1]

    def role_mismatch(
        self, clock: int | None, lang: str, setting: str, seen: str
    ) -> dict[str, Any] | None:
        """Once per match, from ROLE_CHECK_FROM: the role chosen in the settings
        and the one the lane shows differ (live_role.mismatch)."""
        if clock is None or clock < ROLE_CHECK_FROM:
            return None
        start = self._once("role_mismatch", clock, ROLE_CHECK_SHOW)
        if start is None:
            return None
        names = ROLE_NAMES["uk" if lang == "uk" else "en"]
        return _tip(
            "role_mismatch",
            f"role_mismatch@{start}",
            lang,
            setting=names.get(setting, setting),
            seen=names.get(seen, seen),
        )

    def _once(self, key: str, clock: int, show: int) -> int | None:
        """Once per match: the start while within `show` seconds of it."""
        start = self._shown.setdefault(key, clock)
        return start if 0 <= clock - start <= show else None

    def _key_item(
        self, clock: int, lang: str, item: dict[str, Any], items: list[str]
    ) -> dict[str, Any] | None:
        """Once per match: the key item finished 2+ minutes before its typical
        time, or not finished 2 minutes after it."""
        typical = int(item["typical_t"])
        params = {"item": item["name"], "time": clock_label(typical)}
        for key in ("item_early", "item_late"):
            if key in self._shown:
                start = self._once(key, clock, KEY_ITEM_SHOW)
                return _tip(key, f"{key}@{start}", lang, **params) if start is not None else None
        has_it = f"item_{item['key']}" in items
        if has_it and clock <= typical - KEY_ITEM_EARLY:
            key = "item_early"
        elif not has_it and clock >= typical + KEY_ITEM_LATE:
            key = "item_late"
        else:
            if has_it:
                self._shown["item_on_time"] = clock  # bought: never "late" later on
            return None
        if "item_on_time" in self._shown:
            return None
        start = self._once(key, clock, KEY_ITEM_SHOW)
        return _tip(key, f"{key}@{start}", lang, **params) if start is not None else None

    def _mid(
        self, clock: int, lang: str, last_hits: int | None, items: list[str] | None
    ) -> dict[str, Any] | None:
        if last_hits is not None:
            for at, target in MID_LAST_HIT_CHECKS.items():
                if at <= clock <= at + MID_LAST_HIT_SHOW and last_hits < target:
                    key = f"mid_last_hits@{at}"
                    # The count of the first second shown stays on the card.
                    shown = self._shown.setdefault(key, last_hits)
                    return _tip(
                        "mid_last_hits",
                        key,
                        lang,
                        last_hits=shown,
                        last_hits_word=_ru_plural(shown, "добивання", "добивання", "добивань"),
                        time=clock_label(at),
                        target=target,
                    )
        if items is not None and BOTTLE_FROM <= clock <= BOTTLE_UNTIL:
            if not BOTTLE_ITEMS & set(items):
                start = self._once("mid_bottle", clock, BOTTLE_SHOW)
                if start is not None:
                    return _tip("mid_bottle", f"mid_bottle@{start}", lang)
        return None

    def _offlane(
        self, clock: int, lang: str, deaths: int | None, level: int | None
    ) -> dict[str, Any] | None:
        key = "offlane_hard_lane"
        if key not in self._shown:
            if not HARD_LANE_FROM <= clock <= HARD_LANE_UNTIL:
                return None
            lost = (deaths is not None and deaths >= HARD_LANE_DEATHS) or (
                clock >= HARD_LANE_LEVEL_AT and level is not None and level < HARD_LANE_LEVEL
            )
            if not lost:
                return None
        start = self._once(key, clock, HARD_LANE_SHOW)
        return _tip(key, f"{key}@{start}", lang) if start is not None else None


def _ru_plural(count: int, one: str, few: str, many: str) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return one
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return few
    return many


def _tip(
    key: str,
    hint_id: str,
    lang: str,
    at: int | None = None,
    clock: int | None = None,
    **params: Any,
) -> dict[str, Any]:
    title, hint = TIPS[key]["uk" if lang == "uk" else "en"]
    if params:
        title, hint = title.format(**params), hint.format(**params)
    return {
        "kind": "tip",
        "id": hint_id,
        "at": at,
        "at_label": clock_label(at) if at is not None else None,
        "in_seconds": at - clock if at is not None and clock is not None else None,
        "title": title,
        "hint": hint,
        "speak": False,
    }


def _invisible_enemy(enemies: list[str] | None) -> str | None:
    """The first enemy hero seen that goes invisible (draft_analysis.COUNTERS)."""
    from app.draft_analysis import COUNTERS  # a heavy import, only when enemies are known

    if not enemies:
        return None
    heroes = COUNTERS["invisibility"][0]
    return next((e for e in enemies if isinstance(e, str) and e in heroes), None)


def _ward_bag_tip(
    hint_id: str, lang: str, clock: int, score_gap: int | None, roshan_open: bool
) -> dict[str, Any]:
    """Where the ward in the bag should go: Roshan's pit while he can be up, the
    lane's river in the laning stage, the own or the enemy jungle by the kill score."""
    if roshan_open:
        return _tip("ward_bag_roshan", hint_id, lang)
    if clock < WARD_LANING_END:
        return _tip("ward_bag_lane", hint_id, lang)
    if score_gap is not None and clock >= WARD_SCORE_FROM:
        if score_gap <= -WARD_SCORE_GAP:
            return _tip("ward_bag_behind", hint_id, lang, gap=-score_gap)
        if score_gap >= WARD_SCORE_GAP:
            return _tip("ward_bag_ahead", hint_id, lang, gap=score_gap)
    return _tip("ward_bag", hint_id, lang)


def score_gap(extra: dict[str, Any]) -> int | None:
    """The player's team kills minus the enemy's, from live GSI; None unknown."""
    team = str(extra.get("team_name") or "").strip().lower()
    radiant, dire = extra.get("radiant_score"), extra.get("dire_score")
    if team not in ("radiant", "dire") or not isinstance(radiant, int):
        return None
    if not isinstance(dire, int) or isinstance(radiant, bool) or isinstance(dire, bool):
        return None
    return radiant - dire if team == "radiant" else dire - radiant


def _save_item_tip(
    hint_id: str, lang: str, item: dict[str, Any] | None, gold: int
) -> dict[str, Any]:
    """The save item against the enemy lineup, the hero's usual one with its
    price, else Glimmer Cape or Force Staff."""
    why = (item or {}).get("why")
    if why in ("magic", "physical") and item and item.get("name"):
        left = item.get("gold_left")
        if isinstance(left, int) and left <= gold:
            return _tip("save_item_now_lineup", hint_id, lang, item=item["name"])
        return _tip(
            f"save_item_{why}",
            hint_id,
            lang,
            item=item["name"],
            count=item.get("count"),
            enemy=item.get("enemy"),
        )
    if not item or not item.get("name") or not isinstance(item.get("gold_left"), int):
        return _tip("save_item", hint_id, lang)
    left = item["gold_left"]
    if left <= gold:
        return _tip("save_item_now", hint_id, lang, item=item["name"])
    # The gold carried counts too: only the rest is still to farm.
    return _tip("save_item_hero", hint_id, lang, item=item["name"], left=left - gold)


def map_hint(
    clock: int | None,
    role: str | None,
    tips: RoleTips,
    *,
    alive: bool,
    has_ward: bool | None,
    lang: str,
    tp_missing: bool = False,
    carry_advisor: bool = False,
    last_hits: int | None = None,
    level: int | None = None,
    deaths: int | None = None,
    gold: int | None = None,
    lane: str | None = None,
    items: list[str] | None = None,
    key_item: dict[str, Any] | None = None,
    objective: dict[str, Any] | None = None,
    ward_charges: int | None = None,
    skill: dict[str, Any] | None = None,
    save_item: dict[str, Any] | None = None,
    score_gap: int | None = None,
    roshan_open: bool = False,
    enemies: list[str] | None = None,
    bottle_rune: str | None = None,
    denies: int | None = None,
    hp: int | None = None,
    regen: list[str] | None = None,
    missing: dict[str, Any] | None = None,
    lane_record: dict[str, Any] | None = None,
    draft_item: dict[str, Any] | None = None,
    plan_note: dict[str, Any] | None = None,
    enemy_group: dict[str, Any] | None = None,
    fight: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """A timer, but a role tip over a minor one (runes, lotus); None before the
    horn or without a role. `objective`: a Roshan / Aegis timer (roshan_timer.py),
    which wins over a scheduled timer that is not sooner. `skill`: a skill-point
    tip (skill_tips.py), which wins over any scheduled timer: it takes a second
    and the timers stay on the strip under the card."""
    if clock is None or clock < 0 or role is None:
        # Before the horn (or with no role yet) only the skill point: the first
        # one is usually spent then.
        return skill if clock is not None and objective is None else None
    tips.observe_level(level)
    tips.observe_bottle(bottle_rune, clock)
    if skill is not None and objective is None:
        return skill
    # A missing enemy (enemy_lanes.py) is a danger now: over any scheduled timer.
    called = tips.missing(clock, lang, missing if alive else None)
    if called is not None:
        return called
    # A fight elsewhere, then enemies grouped far away (over scheduled timers).
    fought = tips.fight(clock, lang, fight if alive else None)
    if fought is not None:
        return fought
    grouped = tips.enemy_group(clock, lang, enemy_group if alive else None)
    if grouped is not None:
        return grouped
    # The short-term plan that just changed (live_plan.py), over scheduled timers.
    planned = tips.plan(clock, lang, plan if alive else None)
    if planned is not None:
        return planned
    timer = next_timer(clock, role, lang)
    if objective is not None and (
        timer is None
        or timer["minor"]
        or objective.get("urgent")
        or objective["in_seconds"] <= timer["in_seconds"]
    ):
        timer = objective
    if (
        timer is not None
        and role == "mid"
        and timer["id"].startswith("power_rune@")
        and bottle_rune in POWER_RUNES
    ):
        # The Bottle holds one rune: the one in it has to go before the next.
        key = "uk" if lang == "uk" else "en"
        timer["hint"] = TIPS["mid_rune_full"][key][1].format(
            rune=bottle_rune, rune_uk=RUNES_UK.get(bottle_rune, bottle_rune)
        )
    elif (
        timer is not None
        and role == "mid"
        and timer["id"].startswith("power_rune@")
        and level is not None
    ):
        if level >= POWER_SPIKE_LEVEL:
            # With level 6 a power rune is the mid's rotation.
            timer["hint"] = TIPS["mid_rune"]["uk" if lang == "uk" else "en"][1]
        elif items is not None and BOTTLE_ITEMS & set(items):
            # Before it (a known level only), a Bottle keeps the rune for a kill.
            timer["hint"] = TIPS["mid_rune_bottle"]["uk" if lang == "uk" else "en"][1]
    if timer is not None and not timer["minor"]:
        return timer
    tip = tips.tip(
        clock,
        role,
        alive=alive,
        has_ward=has_ward,
        lang=lang,
        tp_missing=tp_missing,
        carry_advisor=carry_advisor,
        last_hits=last_hits,
        level=level,
        deaths=deaths,
        gold=gold,
        lane=lane,
        items=items,
        key_item=key_item,
        ward_charges=ward_charges,
        save_item=save_item,
        score_gap=score_gap,
        roshan_open=roshan_open,
        enemies=enemies,
        denies=denies,
        hp=hp,
        regen=regen,
        lane_record=lane_record,
        draft_item=draft_item,
        plan_note=plan_note,
    )
    return tip or timer
