"""The offline walk-grid builder (scripts/build_walk_grid.py) on a tiny SYNTHETIC
recording: an ally's walk draws its cells, a blink draws none, creeps draw the
cell they stand in, and the recorded player is left out unless asked."""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_walk_grid import CELL, CELLS, cell_of, rows, walked  # noqa: E402

C = 16384


def unit(image: str, name: str, x: float, y: float, team: int = 2) -> dict[str, Any]:
    return {"image": image, "unitname": name, "team": team, "xpos": x - C, "ypos": y - C}


def recording(tmp_path: Path, seconds: list[dict[str, Any]]) -> Path:
    path = tmp_path / "rec.jsonl.gz"
    lines = [{"k": "meta", "hero": "npc_dota_hero_night_stalker"}]
    for clock, minimap in enumerate(seconds, start=600):
        lines.append({"k": "gsi", "p": {"map": {"clock_time": clock}, "minimap": minimap}})
    with gzip.open(path, "wt", encoding="utf-8") as out:
        out.write("".join(json.dumps(line) + "\n" for line in lines))
    return path


def test_walks_draw_their_cells_and_jumps_and_the_player_do_not(tmp_path):
    ally = "npc_dota_hero_juggernaut"
    me = "npc_dota_hero_night_stalker"
    seconds = [
        {
            "a": unit("minimap_herocircle", ally, 12000 + 300 * t, 12000),
            "m": unit("minimap_herocircle_self", me, 20000, 20000 + 300 * t),
            "c": unit("minimap_creep", "npc_dota_creep_badguys_melee", 15000, 9000, 3),
        }
        for t in range(3)
    ]
    # A blink: 3000 units in a second draws nothing between.
    seconds.append({"a": unit("minimap_herocircle", ally, 15600, 12000)})
    cells, counts = walked(recording(tmp_path, seconds), with_player=False)
    assert counts["hero_steps"] == 2 and counts["skipped_jumps"] == 1
    assert {cell_of(12000 + 64 * k, 12000) for k in range(10)} <= cells
    assert cell_of(14000, 12000) not in cells  # between the walk and the blink's end
    assert cell_of(15000, 9000) in cells
    assert cell_of(20000, 20300) not in cells  # the recorded player
    with_me, _ = walked(recording(tmp_path, seconds), with_player=True)
    assert cell_of(20000, 20300) in with_me


def test_rows_are_one_hex_string_per_row_with_bit_i_for_column_i():
    out = rows({(0, 0), (3, 0), (CELLS - 1, 2)})
    assert len(out) == CELLS and all(len(r) == CELLS // 4 for r in out)
    assert int(out[0], 16) == 0b1001 and int(out[2], 16) == 1 << (CELLS - 1)
    assert CELL * CELLS == 16384
