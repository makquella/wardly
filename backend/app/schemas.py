"""
schemas.py — Pydantic models for request and response validation.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.dota_constants import hero_id_from_any, hero_name
from app.hero_profiles import get_hero_position, hero_aliases

SUPPORTED_HEROES = (
    "Anti-Mage",
    "Drow Ranger",
    "Ember Spirit",
    "Gyrocopter",
    "Juggernaut",
    "Kez",
    "Lifestealer",
    "Luna",
    "Medusa",
    "Monkey King",
    "Morphling",
    "Muerta",
    "Naga Siren",
    "Phantom Assassin",
    "Phantom Lancer",
    "Slark",
    "Sniper",
    "Spectre",
    "Sven",
    "Terrorblade",
    "Ursa",
    # Mid and offlane cores (position in hero_profiles.json).
    "Shadow Fiend",
    "Storm Spirit",
    "Queen of Pain",
    "Puck",
    "Templar Assassin",
    "Void Spirit",
    "Outworld Destroyer",
    "Dragon Knight",
    "Axe",
    "Mars",
    "Legion Commander",
    "Bristleback",
    "Centaur Warrunner",
    "Tidehunter",
    "Slardar",
    "Timbersaw",
    "Pangolier",
    "Primal Beast",
    # Supports (position "support" in hero_profiles.json, 4 or 5).
    "Crystal Maiden",
    "Lion",
    "Shadow Shaman",
    "Witch Doctor",
    "Lich",
    "Dazzle",
    "Oracle",
    "Warlock",
    "Jakiro",
    "Vengeful Spirit",
    "Disruptor",
    "Ogre Magi",
    "Treant Protector",
    "Rubick",
    "Earthshaker",
    "Tusk",
    "Earth Spirit",
    "Mirana",
    "Skywrath Mage",
    "Snapfire",
    "Hoodwink",
    "Spirit Breaker",
    "Nyx Assassin",
    "Bounty Hunter",
    "Clockwerk",
)
_SUPPORTED_HERO_LOOKUP = {hero.lower(): hero for hero in SUPPORTED_HEROES}
_SUPPORTED_HERO_LOOKUP.update(
    {
        "npc_dota_hero_antimage": "Anti-Mage",
        "anti mage": "Anti-Mage",
        "npc_dota_hero_drow_ranger": "Drow Ranger",
        "drow": "Drow Ranger",
        "npc_dota_hero_gyrocopter": "Gyrocopter",
        "gyro": "Gyrocopter",
        "npc_dota_hero_juggernaut": "Juggernaut",
        "npc_dota_hero_kez": "Kez",
        "npc_dota_hero_life_stealer": "Lifestealer",
        "life stealer": "Lifestealer",
        "npc_dota_hero_luna": "Luna",
        "npc_dota_hero_medusa": "Medusa",
        "npc_dota_hero_monkey_king": "Monkey King",
        "mk": "Monkey King",
        "npc_dota_hero_morphling": "Morphling",
        "npc_dota_hero_muerta": "Muerta",
        "npc_dota_hero_naga_siren": "Naga Siren",
        "naga": "Naga Siren",
        "npc_dota_hero_phantom_assassin": "Phantom Assassin",
        "pa": "Phantom Assassin",
        "npc_dota_hero_phantom_lancer": "Phantom Lancer",
        "pl": "Phantom Lancer",
        "npc_dota_hero_slark": "Slark",
        "npc_dota_hero_sniper": "Sniper",
        "npc_dota_hero_spectre": "Spectre",
        "npc_dota_hero_sven": "Sven",
        "npc_dota_hero_terrorblade": "Terrorblade",
        "tb": "Terrorblade",
        "npc_dota_hero_ursa": "Ursa",
        "npc_dota_hero_ember_spirit": "Ember Spirit",
        "ember": "Ember Spirit",
    }
)
# Every alias of the profiled heroes (npc names, short names: "sf", "qop", "lc").
_SUPPORTED_HERO_LOOKUP.update(
    {
        alias.lower(): hero
        for hero, aliases in hero_aliases().items()
        if hero in SUPPORTED_HEROES
        for alias in aliases
    }
)


def is_supported_hero(value: str) -> bool:
    """Profiled heroes: the full advisor for a core (farm, items, objectives, hero
    safety), the support advisor for a support (hero_coverage)."""
    return _SUPPORTED_HERO_LOOKUP.get(value.strip().lower()) is not None


def safety_only_hero(value: str) -> str | None:
    """Any other Dota hero gets survival advice only: its canonical name, else None.

    Any spelling of a hero resolves through dota_constants.hero_id_from_any
    (localized "Nature's Prophet", npc "npc_dota_hero_furion", "Furion").
    """
    text = str(value or "").strip()
    if not text or is_supported_hero(text):
        return None
    hero_id = hero_id_from_any(text)
    return hero_name(hero_id) if hero_id is not None else None


def hero_coverage(value: str) -> str | None:
    """ "full" (the core advisor), "support" (a profiled support: survival with its
    own saves, fights and objectives, support tips; no farm or item advice),
    "safety" (survival advice only) or None (not a hero)."""
    if is_supported_hero(value):
        return "support" if get_hero_position(value) == "support" else "full"
    return "safety" if safety_only_hero(value) else None


class GameSituationRequest(BaseModel):
    hero: str = Field(..., min_length=1, description="Hero name, e.g. 'Anti-Mage'")
    role: Literal["carry"] = Field(..., description="Only 'carry' is supported in MVP-1")
    minute: int = Field(..., ge=0, le=90, description="Current game minute (0–90)")
    level: int = Field(..., ge=1, le=30, description="Hero level (1–30)")
    gold: int = Field(..., ge=0, description="Current gold amount")
    items: list[str] = Field(..., description="List of item names the hero currently owns")
    hp_percent: int = Field(..., ge=0, le=100, description="Current HP as a percentage (0–100)")
    game_state: str = Field(
        ..., min_length=1, description="Short description of the current game state"
    )
    team_status: str = Field(
        ..., min_length=1, description="Short description of teammate situation"
    )
    event_context: str = Field("", description="Optional simulation/import context for review")
    near_player_death: bool = Field(False, description="Simulation hint: player death nearby")
    near_teamfight: bool = Field(False, description="Simulation hint: teamfight nearby")
    near_objective: bool = Field(False, description="Simulation hint: objective event nearby")
    selected_team: str = Field("unknown", description="Simulation hint: selected player's team")
    teamfight_result: str = Field("unknown", description="Simulation hint: nearby teamfight result")
    allied_deaths_in_fight: int = Field(
        0, ge=0, description="Simulation hint: allied deaths in nearby teamfight"
    )
    enemy_deaths_in_fight: int = Field(
        0, ge=0, description="Simulation hint: enemy deaths in nearby teamfight"
    )
    recent_allied_deaths: int = Field(
        0, ge=0, description="Simulation hint: allied deaths near timestamp"
    )
    recent_enemy_deaths: int = Field(
        0, ge=0, description="Simulation hint: enemy deaths near timestamp"
    )
    selected_player_death_nearby: bool = Field(
        False, description="Simulation hint: selected player death nearby"
    )
    selected_player_in_teamfight: bool = Field(
        False, description="Simulation hint: selected player participated in nearby teamfight"
    )
    teamfight_start: int | None = Field(
        None, description="Simulation hint: nearby teamfight start time"
    )
    teamfight_end: int | None = Field(
        None, description="Simulation hint: nearby teamfight end time"
    )
    objective_type: str | None = Field(None, description="Simulation hint: nearby objective type")
    objective_team: str | None = Field(
        None, description="Simulation hint: team that secured nearby objective"
    )
    objective_for_selected_team: bool | None = Field(
        None, description="Simulation hint: objective helped selected player's team"
    )
    objective_context: str = Field(
        "unknown", description="Simulation hint: nearby objective context"
    )
    recent_item_purchase: str | None = Field(
        None, description="Simulation hint: recent meaningful item timing"
    )
    item_timing_category: str | None = Field(
        None, description="Simulation hint: item timing category"
    )
    gold_delta: int = Field(0, description="Simulation hint: gold gained since previous interval")
    lh_delta: int = Field(
        0, description="Simulation hint: last hits gained since previous interval"
    )
    farm_rate_state: Literal["good", "slow", "unknown"] = Field(
        "unknown",
        description="Simulation hint: farm pace for this interval",
    )
    extra_context: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional live GSI-only fields that do not belong to the public MVP schema",
    )

    @field_validator("hero")
    @classmethod
    def validate_supported_hero(cls, value: str) -> str:
        hero = value.strip()
        supported_hero = _SUPPORTED_HERO_LOOKUP.get(hero.lower()) or safety_only_hero(hero)
        if supported_hero is None:
            supported = ", ".join(SUPPORTED_HEROES)
            raise ValueError(f"Unknown hero '{value}'. Full advice for: {supported}.")
        return supported_hero

    @field_validator("items")
    @classmethod
    def validate_items(cls, value: list[str]) -> list[str]:
        cleaned_items: list[str] = []
        for item in value:
            cleaned_item = item.strip()
            if not cleaned_item:
                raise ValueError("Items must not contain empty strings.")
            cleaned_items.append(cleaned_item)
        return cleaned_items


class RecommendationResponse(BaseModel):
    action: str
    reason: str
    risk: str
    priority: Literal["low", "medium", "high"]
    time_window: str
    source: Literal["fallback", "llm"] = "fallback"
    # The tool the action orders to use ({kind: item|ability, name}: a GSI item
    # name or the ability's profile name), set by the copy that chose it
    # (live_tools.ToolCopy); None for a card that names none. Internal: not
    # part of the API payload.
    tool: dict[str, Any] | None = Field(default=None, exclude=True)
