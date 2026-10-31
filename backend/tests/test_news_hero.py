"""The hero of the week on the site (scripts/news_hero.py): each pick in
data/news/hero-week.json gets a news page with that week's numbers and the hero
page's advice, and the news list mixes it with the other posts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import news  # noqa: E402 - scripts/news.py
import news_hero  # noqa: E402


def _site():
    return SimpleNamespace(
        ARCHETYPES={"hard_scaling_farmer": ("керрі, що фармить", "a farming carry")},
        NOTES_UK={"Spectre": "Фарми безпечно."},
        NOTES_EN={},
        POSITION_NAMES={"uk": {"carry": "Керрі"}, "en": {"carry": "Carry"}},
    )


def _hero():
    return {
        "name": "Spectre",
        "slug": "spectre",
        "key": "spectre",
        "position": "carry",
        "saves": ["Black King Bar"],
        "pace": [(10, 45, 60)],
        "profile": {
            "archetype": "hard_scaling_farmer",
            "low_hp_warning_threshold": 50,
            "critical_hp_threshold": 35,
            "key_fight_abilities": ["Haunt"],
        },
    }


def test_the_hero_of_the_week_uses_the_meta_post_of_its_week(tmp_path, monkeypatch):
    week = tmp_path / "hero-week.json"
    week.write_text(
        json.dumps(
            {
                "weeks": [
                    {"date": "2026-10-15", "hero": "Spectre"},
                    {"date": "2026-10-16", "hero": "Nobody Without A Page"},
                ]
            }
        )
    )
    monkeypatch.setattr(news_hero, "HERO_WEEK", week)
    newer = {
        "date": "2026-10-19",
        "from": "2026-10-13",
        "to": "2026-10-19",
        "heroes": [{"key": "spectre", "picks": 10, "wins": 1}],
    }
    older = {
        "date": "2026-10-12",
        "from": "2026-10-06",
        "to": "2026-10-12",
        "heroes": [
            {"key": "spectre", "picks": 100, "wins": 55},
            {"key": "x", "picks": 900, "wins": 450},
        ],
    }
    entries = news_hero.entries([_hero()], [newer, older])
    assert len(entries) == 1
    entry = entries[0]
    assert entry["post"] is older and entry["stats"] == {"win": 0.55, "pick": 1.0}
    fact = news_hero.facts(entry["hero"], _site(), "uk")
    page = news_hero.post_main(entry, fact, "uk", "../", "../", {"spectre"})
    assert "Герой тижня: Spectre" in page and "Керрі, що фармить." in page
    # Spectre has a plan: the numbers that win on him, not the generic thresholds.
    assert "Що виграє на цьому герої" in page and "Прокачка:" in page
    assert "лігові матчі патча" in page and "Відходь, коли HP" not in page
    assert 'href="../heroes/spectre.html"' in page
    # Without a plan the page keeps the hero page's thresholds and pace.
    plain = news_hero.post_main(entry, {**fact, "insights": None}, "uk", "../", "../", set())
    assert "Відходь, коли HP нижче 50 %; нижче 35 % — негайно." in plain
    assert "До 10:00 — 45–60 добивань." in plain
    assert "6–12 жовтня" in page
    # No English note for the hero: the English page just leaves it out.
    en = news_hero.post_main(
        entry, news_hero.facts(entry["hero"], _site(), "en"), "en", "../", "../../"
    )
    assert "Hero of the week: Spectre" in en and "Фарми" not in en
    assert news_hero.slug(entry) == "2026-10-15-hero-spectre"
    item = news_hero.list_item(entry, fact, "uk", "", {"spectre"})
    assert 'href="news/2026-10-15-hero-spectre.html"' in item
    assert "Керрі · 55,0 % перемог" in item and "assets/heroes/spectre.webp" in item


def test_the_news_list_takes_the_heroes_between_the_other_posts():
    meta = {
        "date": "2026-10-12",
        "from": "2026-10-06",
        "to": "2026-10-12",
        "heroes": [
            {"name": f"Hero {i}", "key": "", "picks": 1000, "wins": 500 + i} for i in range(20)
        ],
    }
    extra = [
        ("2026-10-15", '<a href="news/b.html"></a>'),
        ("2026-09-15", '<a href="news/a.html"></a>'),
    ]
    page = news.list_main([meta], "uk", "./", "", set(), None, extra)
    order = [
        page.index(href) for href in ("news/b.html", "news/2026-10-12-meta.html", "news/a.html")
    ]
    assert order == sorted(order)
