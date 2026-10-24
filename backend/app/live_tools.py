"""
live_tools.py - what the player can press right now, for the survival advice.

The survival cards ("Leave the wave and reset HP", "Wait out the disable",
"After respawn, change your route") were the same every time. With the live
GSI items they can name the tool that is ready:

- low HP: an escape (Force Staff, Eul's, Ghost Scepter…), an instant heal
  (Magic Wand with its charges, Satanic, Faerie Fire…) or regen to use out of
  sight (Healing Salve, Tango, Bottle);
- a disable: what dispels it or gets out once it ends (Black King Bar, Manta
  Style, Lotus Orb…); a silence alone does not stop items, so then "now";
- a death: the rescue item that was ready and not pressed in the last seconds
  (last_moments.py, from the match recording).

Only what GSI reports as ready counts (last_moments.ready_savers: castable, off
cooldown, a Magic Wand from 10 charges); without an items block nothing is
claimed and the plain text stays.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.hero_profiles import find_ability, get_key_safety_abilities
from app.last_moments import (
    BOTTLE_RUNES,
    RUNE_ESCAPES,
    active_slot,
    held_rune,
    is_saver,
    saver_label,
)
from app.status_source import is_threat
from app.team_context import contest_near, steady_allies

# Low HP: first a way out, then an instant heal.
ESCAPES = (
    "item_force_staff",
    "item_hurricane_pike",
    "item_cyclone",
    "item_wind_waker",
    "item_ghost",
    "item_glimmer_cape",
    "item_invis_sword",
    "item_silver_edge",
    "item_manta",
    "item_blink",
    "item_swift_blink",
    "item_arcane_blink",
    "item_overwhelming_blink",
    "item_black_king_bar",
)
# Only real instant heals: Satanic and Bloodstone heal through lifesteal while
# attacking or casting, so "press it and step back" would heal nothing.
INSTANT_HEALS = (
    "item_magic_wand",
    "item_guardian_greaves",
)
# Consumables that heal: instant first, then over time (use out of sight).
REGEN_INSTANT = {"item_faerie_fire": "Faerie Fire", "item_cheese": "Cheese"}
REGEN_OVER_TIME = {
    "item_flask": "Healing Salve",
    "item_bottle": "Bottle",
    "item_tango": "Tango",
    "item_tango_single": "Tango",
}
# Runes that make a kill: held in the Bottle they wait for one (map_hints).
POWER_RUNES = {"Haste", "Double Damage", "Arcane", "Invisibility", "Illusion", "Shield"}
# A disable: what removes it or gets out the moment it ends.
DISPELS = (
    "item_black_king_bar",
    "item_manta",
    "item_lotus_orb",
    "item_cyclone",
    "item_wind_waker",
    "item_satanic",
    "item_guardian_greaves",
    "item_disperser",
)

# Profile abilities that can be pressed as a save right now: no target needed
# (or a point / self cast) and not passive. Target-dependent skills (Sunder,
# Phantom Strike, Tree Dance, Fire Remnant), passives (Dispersion, Mana Shield)
# and toggles (Attribute Shift) never count, in live advice or as "unpressed".
USABLE_SAFETY = {
    "blink",
    "blade fury",
    "rage",
    "shadow dance",
    "dark pact",
    "pounce",
    "waveform",
    "blur",
    "gust",
    "warcry",
    "grappling claw",
    "raptor dance",
    "enrage",
    "mischief",
    "doppelganger",
    "mirror image",
    "song of the siren",
    "concussive grenade",
    "pierce the veil",
    "flame guard",
    "sleight of fist",
    # Mid and offlane cores.
    "ball lightning",
    "phase shift",
    "refraction",
    "dissimilate",
    "stampede",
    "guardian sprint",
    "timber chain",
    "swashbuckle",
    # Supports: escapes and saves on self (Shallow Grave, False Promise, Frost
    # Shield and Living Armor can be cast on yourself).
    "leap",
    "scurry",
    "bulldoze",
    "vendetta",
    "spiked carapace",
    "shadow walk",
    "rolling boulder",
    "firesnap cookie",
    "shallow grave",
    "false promise",
    "frost shield",
    "living armor",
}

LOW_HP_ACTION_TYPES = {
    "retreat_reset",
    "play_back_and_regen",
    "stop_overstay_low_hp",
    "stabilize_after_recent_damage",
}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return 0
    return int(value) if 0 <= value < 1000 else 0


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return float(value)


def hero_tools(hero: Any, abilities: Any) -> dict[str, Any]:
    """The hero's own escape and defensive abilities (hero_profiles.json) from the
    live GSI abilities: `ready` [(name, kind)] — learned, off cooldown and not
    marked uncastable — escapes first, and `cooldowns` {name: seconds left}."""
    ready: list[tuple[str, str]] = []
    cooldowns: dict[str, int] = {}
    if not isinstance(hero, str) or not hero or not isinstance(abilities, list):
        return {"ready": ready, "cooldowns": cooldowns}
    key = get_key_safety_abilities(hero)
    for kind in ("escape", "defensive"):
        for name in key[kind]:
            if name.lower() not in USABLE_SAFETY:
                continue
            ability = find_ability(abilities, name)
            if not ability or not (_number(ability.get("level")) or 0) > 0:
                continue
            cooldown = _number(ability.get("cooldown"))
            if cooldown is not None and cooldown > 0:
                cooldowns[name] = int(-(-cooldown // 1))
            elif ability.get("can_cast") is not False and cooldown is not None:
                ready.append((name, kind))
    return {"ready": ready, "cooldowns": cooldowns}


def ready_abilities(hero: Any, abilities: Any) -> list[str]:
    """Names of the hero's safety abilities that could be pressed now."""
    return [name for name, _ in hero_tools(hero, abilities)["ready"]]


def bottle_rune(items: Any) -> str | None:
    """The rune held in a Bottle in the inventory (BOTTLE_RUNES name); None
    without one, with an empty Bottle or with a rune name not known here."""
    for slot, value in _dict(items).items():
        rune = held_rune(_dict(value)) if active_slot(slot) else None
        if rune is not None:
            return rune
    return None


def regen_items(items: Any) -> list[str] | None:
    """Healing consumables in the inventory that can be used (None: no items block).
    A Bottle holding a rune heals only with a Regeneration or Water rune: pressed,
    it uses the rune, not a charge."""
    if not isinstance(items, dict) or not items:
        return None
    found: list[str] = []
    for slot, value in items.items():
        item = _dict(value)
        name = item.get("name")
        if not active_slot(slot) or not isinstance(name, str) or name in found:
            continue
        if name not in REGEN_INSTANT and name not in REGEN_OVER_TIME:
            continue
        if item.get("can_cast") is False:
            continue
        if name == "item_bottle":
            rune = item.get("contains_rune")
            held = BOTTLE_RUNES.get(rune.lower()) if isinstance(rune, str) else None
            if held is None and rune not in (None, "", "empty"):
                continue  # an unknown rune: pressing it uses the rune
            if held is None and _count(item.get("charges")) < 1:
                continue
            if held is not None and held not in ("Regeneration", "Water"):
                continue
        found.append(name)
    return found


def wand_charges(items: Any) -> int | None:
    for slot, value in _dict(items).items():
        item = _dict(value)
        if active_slot(slot) and item.get("name") == "item_magic_wand":
            return _count(item.get("charges"))
    return None


def _label(name: str) -> str:
    if is_saver(name):
        return saver_label(name, "en")
    return REGEN_INSTANT.get(name) or REGEN_OVER_TIME.get(name) or name


def _first(ready: list[str], order: tuple[str, ...]) -> str | None:
    return next((name for name in order if name in ready), None)


def _ready(extra: Mapping[str, Any]) -> list[str] | None:
    ready = extra.get("ready_savers")
    if not isinstance(ready, list):
        return None
    return [name for name in ready if isinstance(name, str)]


def _items_blocked(extra: Mapping[str, Any]) -> bool:
    """Stunned, hexed or muted: no item can be used right now."""
    return any(extra.get(flag) is True for flag in ("stunned", "hexed", "muted"))


def _abilities_blocked(extra: Mapping[str, Any]) -> bool:
    """Stunned, hexed or silenced: no ability can be cast (a mute stops items only)."""
    return any(extra.get(flag) is True for flag in ("stunned", "hexed", "silenced"))


def _own_ready(extra: Mapping[str, Any], hero: Any) -> list[tuple[str, str]]:
    if _abilities_blocked(extra):
        return []
    return hero_tools(hero, extra.get("abilities"))["ready"]


LOW_HP_REPEAT_FROM = 2  # low-HP cards before this one


def hp_falling_reason(extra: Mapping[str, Any]) -> str | None:
    """The reason of a low-HP card raised by HP falling fast (match_memory
    hp_falling_fast) rather than by HP already under the line. It states what
    was measured (the loss, and that it has not stopped) and projects nothing:
    a finished combo is not a constant DPS, so no «seconds left»."""
    lost = extra.get("hp_falling_fast")
    if not isinstance(lost, int) or isinstance(lost, bool) or lost <= 0:
        return None
    return f"You lost {lost}% HP in 5 seconds and it is still dropping."


def low_hp_repeat_reason(extra: Mapping[str, Any]) -> str | None:
    """The reason of a low-HP card that has come before in this match: the same
    «use Blink now» a fifth time says nothing new, how often it happens does."""
    before = extra.get("low_hp_before")
    if not isinstance(before, int) or isinstance(before, bool) or before < LOW_HP_REPEAT_FROM:
        return None
    reason = (
        f"Your HP has dropped this low {before + 1} times this game: "
        "heal up fully before you go back."
    )
    regen = extra.get("regen_items")
    if isinstance(regen, list) and not regen:
        reason += " No regen in your bag: have the courier bring a Healing Salve."
    return reason


# Critical HP is not the same danger for every hero: these own resources make a
# death cheaper or low HP part of the hero's plan. The card names the resource
# and keeps leaving as the default; nothing is claimed about enemies or targets.
INSURANCE_COPY = {
    "item_aegis": (
        "You hold the Aegis: leave unless this fight is worth losing it.",
        "A death now revives you on the spot, but the Aegis is gone after that.",
    ),
    "abaddon_borrowed_time": (
        "Use Borrowed Time before the next burst: damage will heal you.",
        "Borrowed Time is ready: while it lasts, incoming damage heals you instead.",
    ),
    "terrorblade_sunder": (
        "If a healthy enemy hero is in range, Sunder swaps your HP with theirs.",
        "Sunder is ready: at low HP it is your save; with no healthy target, leave.",
    ),
    "skeleton_king_reincarnation": (
        "Reincarnation is ready: leave unless this fight is worth spending it.",
        "A death now revives you after a few seconds, but its long cooldown starts.",
    ),
}
# Cast first: an active save, then the swap; revives only make a death cheaper.
CAST_INSURANCE = ("abaddon_borrowed_time", "terrorblade_sunder")


def _ability_by_raw_name(abilities: Any, raw_name: str) -> Mapping[str, Any] | None:
    if not isinstance(abilities, list):
        return None
    return next(
        (a for a in abilities if isinstance(a, Mapping) and a.get("raw_name") == raw_name),
        None,
    )


def _learned_off_cooldown(ability: Mapping[str, Any] | None) -> bool:
    if ability is None or not (_number(ability.get("level")) or 0) > 0:
        return False
    return _number(ability.get("cooldown")) == 0


SUNDER_HP_PERCENT = 40  # above it a swap rarely gives HP back


def insurance_copy(extra: Mapping[str, Any], hp_percent: Any = None) -> tuple[str, str] | None:
    """(action, reason) for critical HP when an observed own resource changes
    what low HP means (INSURANCE_COPY); None without one. A disable keeps the
    post-disable wording, so this only applies when the hero can act."""
    if extra.get("stunned") is True or extra.get("hexed") is True:
        return None
    abilities = extra.get("abilities")
    if not _abilities_blocked(extra):
        for raw_name in CAST_INSURANCE:
            hp = _number(hp_percent)
            if raw_name == "terrorblade_sunder" and (hp is None or hp > SUNDER_HP_PERCENT):
                continue
            ability = _ability_by_raw_name(abilities, raw_name)
            if (
                ability is not None
                and _learned_off_cooldown(ability)
                and ability.get("can_cast") is not False
            ):
                return INSURANCE_COPY[raw_name]
    if extra.get("has_aegis") is True:
        return aegis_copy(extra)
    # Reincarnation triggers on its own (passive): its cooldown is the signal.
    if _learned_off_cooldown(_ability_by_raw_name(abilities, "skeleton_king_reincarnation")):
        return INSURANCE_COPY["skeleton_king_reincarnation"]
    return None


def _running_regen(extra: Mapping[str, Any]) -> set[str]:
    """Healing items whose effect is still running (action_feedback.py): the
    player already used them, so the card does not ask for them again."""
    active = extra.get("regen_active")
    running = {n for n in active if isinstance(n, str)} if isinstance(active, list) else set()
    if "item_tango" in running or "item_tango_single" in running:
        running |= {"item_tango", "item_tango_single"}
    return running


def learned_escapes(hero: Any, abilities: Any) -> list[dict[str, Any]]:
    """The hero's profile escape abilities that are learned (level > 0), with
    their live fields: what a low-mana card may name."""
    if not isinstance(hero, str) or not hero or not isinstance(abilities, list):
        return []
    found = []
    for name in get_key_safety_abilities(hero)["escape"]:
        ability = find_ability(abilities, name)
        if ability and (_number(ability.get("level")) or 0) > 0:
            found.append({**ability, "label": name})
    return found


def low_mana_reason(extra: Mapping[str, Any], hero: Any = None) -> str:
    """Why low mana matters now, from what is learned: an escape that is off
    cooldown yet not castable (and no silence/stun) is short of mana right now;
    a learned escape may be next; with none learned yet no escape is named."""
    escapes = learned_escapes(hero, extra.get("abilities"))
    blocked = _abilities_blocked(extra)
    for ability in escapes:
        if (
            not blocked
            and _number(ability.get("cooldown")) == 0
            and ability.get("can_cast") is False
        ):
            return f"{ability['label']} is off cooldown but cannot be cast now: not enough mana."
    if escapes:
        return f"Low mana can leave {escapes[0]['label']} uncastable in the next fight."
    return "Low mana limits your spells in the next fight."


def _defensive_item_state(extra: Mapping[str, Any]) -> tuple[str, int] | None:
    """(label, seconds left; 0 = ready) of the first escape/dispel item in the
    active slots, from its reported cooldown."""
    cooldowns = extra.get("item_cooldowns")
    if not isinstance(cooldowns, Mapping):
        return None
    for name in (*DISPELS, *ESCAPES):
        cooldown = _number(cooldowns.get(name))
        if cooldown is not None:
            return _label(name), int(-(-cooldown // 1))
    return None


def readiness_copy(
    extra: Mapping[str, Any], ability: str, seconds: int | None
) -> tuple[str, str] | None:
    """After an own kill moments ago (not proof the fight is over) or a revive,
    with a fight still around (team_context.contest_near): the constraint on
    the next engage while the key ability is down, and what the main defensive
    item says. A cooldown coming back is availability, not a reason to go in:
    the card says what to hold until then, never «go in». Only cooldowns GSI
    reports; no claim about enemies' state."""
    after_kill = isinstance(extra.get("recent_kill_seconds"), int)
    revive = extra.get("recent_revive")
    if not after_kill and not isinstance(revive, Mapping) or not seconds:
        return None
    if not contest_near(extra):
        return None
    item = _defensive_item_state(extra)
    item_line = ""
    if item is not None:
        label, left = item
        item_line = f" {label} is ready." if left == 0 else f" {label} is back in {left} s."
    if isinstance(revive, Mapping) and revive.get("type") in {"aegis_revive", "reincarnation"}:
        return (
            f"Second life: hold the next engage until {ability} is back in {seconds} s.",
            f"You revived on the spot.{item_line}",
        )
    return (
        f"After your kill: hold the next engage until {ability} is back in {seconds} s.",
        f"Before it is back you have no way out if the fight turns.{item_line}",
    )


def aegis_copy(extra: Mapping[str, Any]) -> tuple[str, str]:
    """The Aegis card at critical HP with what GSI confirms: how long it still
    lasts (only when its pickup was seen, roshan_timer.py) and the allies on
    the minimap next to the hero; else the plain line. It claims nothing about
    enemies and commands no fight."""
    action, reason = INSURANCE_COPY["item_aegis"]
    left = extra.get("own_aegis_left")
    allies = steady_allies(extra)
    facts = []
    if isinstance(left, int) and not isinstance(left, bool) and 0 < left <= 300:
        facts.append(f"it expires in about {left} s")
    if allies:
        facts.append(f"{len(allies)} {'ally is' if len(allies) == 1 else 'allies are'} next to you")
    if facts:
        reason = f"A death now revives you on the spot; {' and '.join(facts)}."
    return action, reason


# A Wand with this many charges heals enough to name next to an escape.
WAND_WORTH_CHARGES = 5


def low_hp_copy(extra: Mapping[str, Any], hero: Any = None) -> tuple[str, str] | None:
    """(action, reason) naming the tool to press at low HP; None without one.
    Stunned, hexed or muted, no item can be pressed: the post-disable wording."""
    if extra.get("stunned") is True or extra.get("hexed") is True:
        return disabled_copy(extra, hero)
    own = _own_ready(extra, hero)
    if own:
        name, kind = own[0]
        if kind == "escape":
            charges = _count(extra.get("wand_charges"))
            if "item_magic_wand" in (_ready(extra) or []) and charges >= WAND_WORTH_CHARGES:
                # The escape first, and the charged Wand is HP on the way out
                # (PL 12:30: Doppelganger ready, the Wand with charges).
                return (
                    f"Use {name} now to get out, then Magic Wand.",
                    f"Your HP is low and {name} is ready: use it before the next hit. "
                    f"Magic Wand has {charges} charges: press it on the way out.",
                )
            return (
                f"Use {name} now to get out, then reset HP.",
                f"Your HP is low and {name} is ready: use it before the next hit, not after.",
            )
        return (
            f"Use {name} now and walk out of the fight.",
            f"{name} is ready: it buys you the seconds to get away.",
        )
    if _items_blocked(extra):  # muted: the items wait until it ends
        return disabled_copy(extra, hero)
    # Items: only what the GSI items block shows (none → nothing claimed).
    ready = _ready(extra) or []
    escape = _first(ready, ESCAPES)
    if escape:
        name = _label(escape)
        return (
            f"Use {name} now to get out, then reset HP.",
            f"Your HP is low and {name} is ready: use it before the next hit, not after.",
        )
    rune = extra.get("bottle_rune")
    if rune in RUNE_ESCAPES:
        return (
            f"Use the {rune} rune from your Bottle and run.",
            f"The {rune} rune in your Bottle is ready: use it before the next hit, not after.",
        )
    heal = _first(ready, INSTANT_HEALS)
    if heal == "item_magic_wand":
        charges = _count(extra.get("wand_charges"))
        return (
            "Use Magic Wand now, then step back.",
            f"Magic Wand has {charges} charges: that HP is yours right now."
            if charges
            else "Magic Wand is charged: that HP is yours right now.",
        )
    if heal:
        name = _label(heal)
        return (f"Use {name} now, then step back.", f"{name} is ready and heals you at once.")
    regen = extra.get("regen_items")
    running = _running_regen(extra)
    regen = (
        [n for n in regen if isinstance(n, str) and n not in running]
        if isinstance(regen, list)
        else []
    )
    if "item_bottle" in regen and rune == "Water":
        return (
            "Use the Water rune from your Bottle now, then step back.",
            "The Water rune in your Bottle heals you at once.",
        )
    instant = next((n for n in regen if n in REGEN_INSTANT), None)
    if instant:
        name = _label(instant)
        return (f"Use {name} now, then step back.", f"{name} heals you at once.")
    over_time = next((n for n in regen if n in REGEN_OVER_TIME), None)
    if over_time == "item_bottle" and rune == "Regeneration":
        return (
            "Step out of enemy range and use the Regeneration rune from your Bottle.",
            "The Regeneration rune heals fast but stops at the first hit: "
            "use it where enemies cannot reach you.",
        )
    if over_time:
        name = _label(over_time)
        return (
            f"Step out of enemy range and use {name}.",
            f"{name} heals over time: use it where enemies cannot hit you.",
        )
    return None


def disabled_copy(extra: Mapping[str, Any], hero: Any = None) -> tuple[str, str] | None:
    """(action, reason) for a disable when a dispel or escape is ready: a dispel
    item, then the hero's own escape or defensive ability, then an escape item.
    None for a status that is the player's own phase or unexplained (no debuff,
    no HP lost; status_source.py): nothing to dispel, no item to spend."""
    if not is_threat(extra.get("status_source", {"kind": "unknown"})):
        return None
    ready = _ready(extra) or []
    blocked = _items_blocked(extra)
    tool = _first(ready, DISPELS)
    if not blocked and extra.get("silenced") is True and tool:
        name = _label(tool)
        return (
            f"Use {name} now: it removes the silence.",
            "A silence does not stop items: get rid of it before the next spell lands.",
        )
    own = [name for name, _ in _own_ready(extra, hero)]
    if (
        own
        and blocked
        and extra.get("muted") is True
        and not (extra.get("stunned") is True or extra.get("hexed") is True)
    ):
        # Muted only: items wait, the hero's spells do not.
        return (
            f"Use {own[0]} now: a mute blocks items, not spells.",
            f"{own[0]} is ready: it buys you the seconds to get away.",
        )
    if not own:
        own = [n for n, _ in hero_tools(hero, extra.get("abilities"))["ready"]]
    name = _label(tool) if tool else (own[0] if own else None)
    if name is None and _first(ready, ESCAPES):
        name = _label(_first(ready, ESCAPES) or "")
    if not blocked or not name or not _disable_endangers(extra):
        return None
    return (
        f"The moment the disable ends, use {name}.",
        f"{name} is ready: the second after a disable is when most kills finish.",
    )


# «The moment the disable ends, use X» only when the disable puts the life at
# stake: HP at or below this share of max, or this share of max HP lost since
# its onset (status_source `hp_lost_share`, from the snapshot before it). In
# the Phantom Lancer recording the 6 post-disable cards with something at
# stake had HP at 7-51 % around the stun or lost 29-60 % in it; the short stuns
# at 67-94 % HP losing 0-13 % had nothing after them, and a card at +0.5 s on
# a 0.6 s stun arrives when it is over. Checked again every snapshot of the
# status: HP lost later in it brings the card then.
DISABLE_DANGER_HP_SHARE = 0.50
DISABLE_DANGER_LOST_SHARE = 0.15


def _disable_endangers(extra: Mapping[str, Any]) -> bool:
    health, max_health = _number(extra.get("health")), _number(extra.get("max_health"))
    if health is None or not max_health:
        return True  # unknown HP: the legacy card
    if health / max_health <= DISABLE_DANGER_HP_SHARE:
        return True
    source = extra.get("status_source")
    lost = _number(source.get("hp_lost_share")) if isinstance(source, Mapping) else None
    return lost is not None and lost >= DISABLE_DANGER_LOST_SHARE


ZONES = {"top": "top lane", "mid": "mid lane", "bot": "bottom lane", "jungle": "jungle"}
SIDES = {"own": "on your side", "river": "by the river", "enemy": "on the enemy side"}


def death_items_reason(extra: Mapping[str, Any]) -> str | None:
    """The rescue item that was ready and not pressed before the last death."""
    items = extra.get("death_items")
    if not isinstance(items, list):
        return None
    names = [_label(n) for n in items if is_saver(n)]
    if not names:
        return None
    return f"You died with {names[0]} ready: next time use it at the first big hit."


# Deaths in one place over the whole match that make a pattern
# (player_service._death_place `in_match`).
MATCH_PLACE_MIN = 3


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def death_copy(extra: Mapping[str, Any], *, route: bool = True) -> tuple[str | None, str | None]:
    """(action, reason) of a death advice from where it happened and what was
    left unpressed; None for a part that stays as it is.

    Two or more deaths in the same zone and half within ten minutes → stay away
    from there; one death on the enemy half → farm your own half; the unpressed
    item is the lesson and wins the reason."""
    action = reason = None
    place = extra.get("death_place")
    # A spot where the hero died with allies staying next to it is where the
    # team fought, not a route taken alone: no «stay away until your team is
    # there» (match_memory REPEATED_PLACE).
    with_team = extra.get("last_death_with_team") is True
    if (
        isinstance(place, Mapping)
        and place.get("zone") in ZONES
        and place.get("side") in SIDES
        and not with_team
    ):
        where = f"{ZONES[place['zone']]} {SIDES[place['side']]}"
        count = place.get("count") if isinstance(place.get("count"), int) else 1
        minutes = place.get("minutes") if isinstance(place.get("minutes"), int) else 1
        if count >= 2:
            action = f"After respawn, stay away from the {where}."
            noun = "minute" if minutes == 1 else "minutes"
            reason = (
                f"{count} deaths in the {where} in {minutes} {noun}: "
                "farm somewhere safer until your team is there."
            )
        elif _int(place.get("in_match")) >= MATCH_PLACE_MIN:
            action = f"After respawn, stay away from the {where}."
            reason = (
                f"{place['in_match']} deaths in the {where} this game: "
                "farm somewhere safer until your team is there."
            )
        elif place["side"] == "enemy":
            reason = (
                f"You died in the {ZONES[place['zone']]} on the enemy side: "
                "farm your own half until your team is with you."
            )
    # Deaths in different places are several events, not one repeated route:
    # a count alone («3 deaths this game») names no route to change, so the
    # single-death line (where it was, how fast it came) speaks instead.
    if action is None and route:
        action, reason = _single_death_copy(extra, place, reason)
    return action, death_items_reason(extra) or reason


LANES = ("top", "mid", "bot")
LANING_END = 600  # clock seconds: a lane death before this is a laning death


def _single_death_copy(
    extra: Mapping[str, Any], place: Any, reason: str | None
) -> tuple[str | None, str | None]:
    """The first death (or the only one lately): where it was, else how fast it
    came, in place of «plan a safer route»."""
    if isinstance(place, Mapping) and place.get("zone") in ZONES and place.get("side") in SIDES:
        zone, side = ZONES[place["zone"]], place["side"]
        if side == "enemy":
            # The lesson moves into the action; the reason is free for the
            # unpressed item or what to buy.
            return (
                f"After respawn, farm your own half: you died in the {zone} on the enemy side.",
                None,
            )
        clock = extra.get("clock_time")
        if place["zone"] in LANES and isinstance(clock, int) and 0 <= clock < LANING_END:
            return (
                f"After respawn, play the {zone} closer to your tower until you see the enemy heroes.",
                reason,
            )
        return (
            f"After respawn, avoid the {zone} {SIDES[side]} without your team: you died there.",
            reason,
        )
    burst = extra.get("death_burst")
    if isinstance(burst, int) and 1 <= burst <= 5:
        noun = "second" if burst == 1 else "seconds"
        return (
            f"After respawn, stay near your towers or your team: "
            f"you went down in {burst} {noun} from high HP.",
            reason,
        )
    return None, reason
