"""The offline camp-map builder (scripts/build_farm_map.py) on a tiny SYNTHETIC
recording: a camp spawning at the minute on its spot for three minutes gives a
spot; a single wandering unit and a two-minute spot do not."""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_farm_map import observations, parse_kv, spots, valve_units  # noqa: E402

NPC_UNITS = """
"DOTAUnits"
{
    "npc_dota_neutral_kobold"
    {
        "BountyGoldMin"   "20"
        "BountyGoldMax"   "24"
        "StatusHealth"    "240"
        // a comment
    }
    "npc_dota_neutral_black_dragon"
    {
        "BountyGoldMin"   "150"
        "BountyGoldMax"   "170"
        "StatusHealth"    "2000"
        "IsAncient"       "1"
    }
}
"""


def neutral(name: str, x: float, y: float) -> dict[str, Any]:
    return {"image": "minimap_creep", "unitname": name, "team": 4, "xpos": x, "ypos": y}


def payload(clock: int, units: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "map": {"clock_time": clock},
        "minimap": {f"o{i}": unit for i, unit in enumerate(units)},
    }


def recording(tmp_path: Path, minutes: int, at: tuple[float, float]) -> Path:
    camp = [neutral("npc_dota_neutral_kobold", at[0] + 60 * i, at[1]) for i in range(3)]
    lines = []
    for minute in range(1, minutes + 1):
        # Cleared before the minute (empty sample), back at mm:00.
        lines.append({"k": "gsi", "w": minute * 60 - 1, "p": payload(minute * 60 - 1, [])})
        lines.append({"k": "gsi", "w": minute * 60, "p": payload(minute * 60, camp)})
    path = tmp_path / f"match_{minutes}.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as out:
        out.writelines(json.dumps(line) + "\n" for line in lines)
    return path


def test_valve_kv_gives_bounty_hp_and_ancient():
    units = valve_units(NPC_UNITS)
    assert units["npc_dota_neutral_kobold"] == {"bounty": [20, 24], "hp": 240, "ancient": False}
    assert units["npc_dota_neutral_black_dragon"]["ancient"] is True
    assert parse_kv('"a" { "b" "1" }') == {"a": {"b": "1"}}


def test_a_camp_seen_spawning_three_minutes_becomes_a_spot(tmp_path):
    units = valve_units(NPC_UNITS)
    found = observations(recording(tmp_path, 3, (-3000, -4000)))
    assert [o["kind"] for o in found] == ["spawn"] * 3
    [camp] = spots(found, units)
    assert camp["side"] == "radiant" and camp["ancient"] is False
    assert (camp["x"], camp["y"]) == (16384 - 3000 + 60, 16384 - 4000)
    assert camp["gold"] == 66 and camp["hp"] == 720 and camp["spawns_seen"] == 3


def test_two_minutes_are_not_enough(tmp_path):
    found = observations(recording(tmp_path, 2, (3000, 4000)))
    assert spots(found, valve_units(NPC_UNITS)) == []
