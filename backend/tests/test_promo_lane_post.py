"""The community lane post (scripts/promo/lane_post.py): numbers from the files, the
app's own hard/easy call, and a disclosure without a link."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.promo import lane_post  # noqa: E402


def _opponent(hero, hero_id, won, even, lost, gold):
    return {
        "hero": hero,
        "hero_id": hero_id,
        "lanes": won + even + lost,
        "won": won,
        "even": even,
        "lost": lost,
        "gold_diff": gold,
    }


def _files():
    return {
        8: {
            "hero": "Juggernaut",
            "hero_id": 8,
            "position": "carry",
            "lane_role": 1,
            "window_days": 365,
            "generated": "2026-11-08",
            "source": "test",
            "lanes": 1000,
            "baseline": {"won": 300, "even": 500, "lost": 200},
            "opponents": [
                _opponent("Axe", 2, 2, 6, 22, -900),  # hard: 73% lost vs 20%
                _opponent("Tiny", 19, 20, 8, 2, 700),  # easy: 67% won vs 30%
                _opponent("Lion", 26, 3, 6, 4, -100),  # too few lanes
                _opponent("Pudge", 14, 9, 20, 11, -50),  # no clear difference
            ],
        },
        11: {
            "hero": "Shadow Fiend",
            "hero_id": 11,
            "position": "mid",
            "lane_role": 2,
            "window_days": 365,
            "generated": "2026-11-07",
            "source": "test",
            "lanes": 500,
            "baseline": {"won": 100, "even": 300, "lost": 100},
            "opponents": [_opponent("Huskar", 59, 1, 4, 15, -1200)],
        },
    }


def test_rows_use_the_apps_own_call():
    rows = {r["hero"]: r for r in lane_post.collect(_files())}
    jugg = rows["Juggernaut"]
    assert [o["hero"] for o in jugg["hard"]] == ["Axe"]
    assert [o["hero"] for o in jugg["easy"]] == ["Tiny"]
    assert jugg["base_lost"] == 20
    assert [o["hero"] for o in rows["Shadow Fiend"]["hard"]] == ["Huskar"]
    # carries before mids
    assert [r["hero"] for r in lane_post.collect(_files())] == ["Juggernaut", "Shadow Fiend"]


def test_english_post_numbers_and_disclosure():
    text = lane_post.render("en", _files())
    assert text.startswith("# I counted 1,500 lanes")
    assert "for 2 cores" in text
    assert "800+ gold ahead" in text and "at least 15 lanes" in text
    assert "| Juggernaut | 20% | Axe 73% | Tiny 67% |" in text
    assert "| Shadow Fiend | 20% | Huskar 75% | none clear |" in text
    assert "Shadow Fiend (mid) vs Huskar: lost 75% of 20 lanes (usually 20%), −1200 gold" in text
    assert "generated 2026-11-08" in text
    assert "Lion" not in text and "Pudge" not in text
    assert "Wardly" in text
    assert not re.search(r"https?://|luhovyimvp|\.dev\b", text)


def test_ukrainian_post():
    text = lane_post.render("uk", _files())
    assert text.startswith("# Які лінії справді важкі для корів")
    assert "(ліній у вибірці: 1 500)" in text
    assert "| Juggernaut | 20% | Axe 73% | Tiny 67% |" in text
    assert "| Shadow Fiend | 20% | Huskar 75% | чітких немає |" in text
    assert "Shadow Fiend (мід) проти Huskar" in text
    assert not re.search(r"https?://", text)


def test_real_data_renders():
    text = lane_post.render("en")
    assert "| Hero | Usually lost |" in text
    assert len(text) < 40_000  # Reddit's limit for a post body
