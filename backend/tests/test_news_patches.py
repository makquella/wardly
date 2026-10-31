"""Patch posts (scripts/news.py, scripts/build_news.py, scripts/news_cards.py):
Valve's patch notes as the datafeed gives them (ids, no names, HTML in the
notes), with names in both languages, on the site and in Telegram."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import build_news  # noqa: E402 - scripts/build_news.py
import news  # noqa: E402
import news_cards as cards  # noqa: E402

# 2026-09-15 07:00 UTC, the shape of /datafeed/patchnotes?version=7.41f.
STAMP = 1789455600


def _feed(language: str) -> dict:
    uk = language == "ukrainian"
    return {
        "patch_number": "7.41f",
        "patch_name": "7.41f",
        "patch_timestamp": STAMP,
        "general_notes": [
            {
                "title": "Global Changes",
                "generic": [
                    {"indent_level": 1, "note": "Facets removed from the game"},
                    {"indent_level": 2, "note": "Innates <b>stay</b>", "info": "Press ALT"},
                    {"indent_level": 1, "hide_dot": True, "note": "<br>"},
                ],
            }
        ],
        "items": [
            {
                "ability_id": 265,
                "postfix_lines": 2,
                "ability_notes": [
                    {
                        "indent_level": 1,
                        "note": "Регенерацію мани зменшено: +0,8 → +0,6."
                        if uk
                        else "Mana Regen bonus decreased from +0.8 to +0.6",
                    },
                    {"indent_level": 1, "hide_dot": True, "note": "<br>"},
                ],
            },
            {"ability_id": 99999, "ability_notes": [{"indent_level": 1, "note": "unknown"}]},
        ],
        "neutral_items": [
            {"ability_id": -1, "title": "Enchantment Changes", "is_general_note": True},
            {
                "ability_id": 1593,
                "ability_notes": [
                    {
                        "indent_level": 1,
                        "note": "<font color='#e03e2e'>Attack Damage Penalty</font> increased",
                    }
                ],
            },
        ],
        "heroes": [
            {
                "hero_id": 1,
                "abilities": [
                    {
                        "ability_id": 5003,
                        "ability_notes": [
                            {"indent_level": 1, "note": "Mana Burned as Damage increased"}
                        ],
                    }
                ],
            },
            {
                "hero_id": 3,
                "hero_notes": [{"indent_level": 1, "note": "Base Armor decreased by 1"}],
                "talent_notes": [{"indent_level": 1, "note": "Level 10 Talent changed"}],
            },
            {"hero_id": 404, "hero_notes": [{"indent_level": 1, "note": "no such hero"}]},
        ],
        "success": True,
    }


def _names(language: str) -> dict:
    uk = language == "ukrainian"
    return {
        "heroes": {
            1: {"name": "Anti-Mage", "key": "antimage"},
            3: {"name": "Bane", "key": "bane"},
        },
        "abilities": {5003: "Спалення мани" if uk else "Mana Break"},
        "items": {265: "Infused Raindrops", 1593: "Жадібне" if uk else "Greedy"},
    }


def _patch() -> dict:
    return news.patch_post(
        {lang: _feed(language) for lang, language in news.FEED_LANGUAGES.items()},
        {lang: _names(language) for lang, language in news.FEED_LANGUAGES.items()},
    )


def test_a_patch_post_names_every_id_and_keeps_the_notes_as_plain_text():
    patch = _patch()
    assert patch["version"] == "7.41f" and patch["date"] == "2026-09-15"
    uk, en = patch["languages"]["uk"], patch["languages"]["en"]
    assert en["general"] == [
        {
            "title": "Global Changes",
            "notes": [
                {"level": 1, "text": "Facets removed from the game"},
                {"level": 2, "text": "Innates stay", "info": "Press ALT"},
            ],
        }
    ]
    # Unknown ids and the <br> spacer lines are left out.
    assert [item["name"] for item in en["items"]] == ["Infused Raindrops"]
    assert len(en["items"][0]["notes"]) == 1
    assert uk["items"][0]["notes"][0]["text"].startswith("Регенерацію мани")
    assert en["neutral"] == [
        {"group": "Enchantment Changes", "notes": []},
        {"name": "Greedy", "notes": [{"level": 1, "text": "Attack Damage Penalty increased"}]},
    ]
    assert uk["neutral"][1]["name"] == "Жадібне"
    assert [hero["name"] for hero in en["heroes"]] == ["Anti-Mage", "Bane"]
    anti_mage, bane = uk["heroes"]
    assert anti_mage["abilities"][0]["name"] == "Спалення мани"
    assert bane["notes"][0]["text"] == "Base Armor decreased by 1"
    assert bane["talents"][0]["text"] == "Level 10 Talent changed"
    assert news.patch_counts(patch) == {"heroes": 2, "items": 1, "neutral": 1, "general": 1}


def test_a_broken_answer_is_not_a_patch():
    names = {lang: _names(language) for lang, language in news.FEED_LANGUAGES.items()}
    no_version = {
        lang: {**_feed(lang), "patch_number": None, "patch_name": None} for lang in ["uk", "en"]
    }
    with pytest.raises(ValueError):
        news.patch_post(no_version, names)
    empty = {
        lang: {"patch_number": "7.41f", "patch_timestamp": STAMP, "success": True}
        for lang in ("uk", "en")
    }
    with pytest.raises(ValueError):
        news.patch_post(empty, names)


def test_the_patch_page_and_the_news_list():
    patch = _patch()
    page = news.patch_main(patch, "uk", {"Bane": "bane"}, "../", "../", {"antimage"})
    assert "Патч 7.41f" in page and "Спалення мани" in page and "Таланти" in page
    assert 'src="../assets/heroes/antimage.webp"' in page
    assert 'href="../heroes/bane.html"' in page
    assert "https://www.dota2.com/patches/7.41f" in page
    assert "<font" not in page and "<br>" not in page
    english = news.patch_main(patch, "en", {}, "../", "../", set())
    assert "Patch 7.41f" in english and "Mana Break" in english
    assert "%2Fen%2Fnews%2F2026-09-15-patch-7-41f.html" in english  # the share link

    stats = [
        {
            "id": index + 1,
            "localized_name": f"Hero {index}",
            "pub_pick_trend": [1000] * 7,
            "pub_win_trend": [500] * 7,
        }
        for index in range(60)
    ]
    post = news.meta_post(stats, date(2026, 10, 12))
    listing = news.list_main([post], "uk", "./", "", set(), [patch])
    newest, older = listing.index("2026-10-12-meta.html"), listing.index("2026-09-15-patch-7-41f")
    assert newest < older
    assert "Героїв змінено: 2 · предметів: 1" in listing


def test_the_telegram_patch_post_shows_what_changed_and_links_the_page():
    patch = _patch()
    top = news.patch_highlights(patch)
    assert [row["name"] for row in top["heroes"]] == ["Bane", "Anti-Mage"]  # most notes first
    assert top["heroes"][1]["line"] == "Спалення мани: Mana Burned as Damage increased"
    caption = cards.patch_caption(patch)
    assert cards.visible_length(caption) <= cards.CAPTION_LIMIT
    assert "7.41f" in caption.split("\n")[0]
    assert "<b>Bane</b> — Base Armor decreased by 1" in caption
    assert "<b>Infused Raindrops</b> — Регенерацію мани зменшено: +0,8 → +0,6." in caption
    assert "/news/2026-09-15-patch-7-41f.html?ref=tg" in caption
    assert "https://www.dota2.com/patches/7.41f" in caption and caption.endswith("#патч")
    card = cards.patch_card(patch)
    assert "7.41f" in card and "Anti-Mage" in card and "Base Armor" in card
    assert "{pill}" not in card

    # A long change is cut; many heroes: the caption and the card stay in their limits.
    many = json.loads(json.dumps(patch))
    hero = many["languages"]["uk"]["heroes"][0]
    long_note = [{"level": 1, "text": "Дуже довга зміна " * 20}]
    many["languages"]["uk"]["heroes"] = [
        {**hero, "name": f"A very long hero name {i}", "notes": long_note, "abilities": []}
        for i in range(120)
    ]
    line = news.patch_highlights(many)["heroes"][0]["line"]
    assert len(line) <= 110 and line.endswith("…")
    assert cards.visible_length(cards.patch_caption(many)) <= cards.CAPTION_LIMIT
    assert "та ще" in cards.patch_caption(many)
    assert "+110" in cards.patch_card(many)  # 3 changes, 7 faces and the rest


def _fake_feed(calls: list[str], *, ukrainian: bool = True):
    def fetch(path: str) -> dict:
        calls.append(path)
        if path.startswith("patchnoteslist"):
            return {
                "patches": [
                    {"patch_number": "7.41e", "patch_timestamp": STAMP - 3_000_000},
                    {"patch_number": "7.41f", "patch_timestamp": STAMP},
                ],
                "success": True,
            }
        language = path.split("language=")[1]
        if language == "ukrainian" and not ukrainian:
            raise OSError("HTTP 500")
        if path.startswith("patchnotes?"):
            return _feed(language)
        name = path.split("?")[0]
        names = _names(language)
        if name == "herolist":
            rows = [
                {"id": hero_id, "name": f"npc_dota_hero_{h['key']}", "name_loc": h["name"]}
                for hero_id, h in names["heroes"].items()
            ]
            return {"result": {"data": {"heroes": rows}}}
        source = names["abilities"] if name == "abilitylist" else names["items"]
        rows = [{"id": key, "name_loc": value} for key, value in source.items()]
        return {"result": {"data": {"itemabilities": rows}}}

    return fetch


def test_write_patch_adds_the_newest_and_refreshes_it_for_a_week(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "PATCHES", tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(build_news, "fetch_feed", _fake_feed(calls))

    post, new, changed = build_news.write_patch(None, date(2026, 9, 15))
    assert (post["version"], new, changed) == ("7.41f", True, True)
    stored = tmp_path / "2026-09-15-7.41f.json"
    assert json.loads(stored.read_text(encoding="utf-8")) == post
    assert "patchnotes?version=7.41f&language=ukrainian" in calls

    # Inside the week: fetched again, unchanged, not new.
    assert build_news.write_patch(None, date(2026, 9, 20))[1:] == (False, False)
    # After it: not fetched at all.
    calls.clear()
    assert build_news.write_patch(None, date(2026, 10, 16))[1:] == (False, False)
    assert not any(call.startswith("patchnotes?") for call in calls)


def test_two_patches_between_polls_are_both_posted_oldest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "PATCHES", tmp_path)
    released = {"7.41e": "2026-09-01", "7.41f": "2026-09-15", "7.41g": "2026-09-15"}
    monkeypatch.setattr(build_news, "patch_list", lambda: [(day, v) for v, day in released.items()])

    def fetch_patch(version: str) -> dict:
        return {"kind": "patch", "version": version, "date": released[version], "languages": {}}

    monkeypatch.setattr(build_news, "fetch_patch", fetch_patch)
    today = date(2026, 9, 15)
    (tmp_path / "2026-09-01-7.41e.json").write_text(
        json.dumps(fetch_patch("7.41e")), encoding="utf-8"
    )

    first, new, _ = build_news.write_patch(None, today)
    assert (first["version"], new) == ("7.41f", True)
    second, new, _ = build_news.write_patch(None, today)
    assert (second["version"], new) == ("7.41g", True)
    # Both stored: the newest is refreshed, nothing is new.
    third, new, _ = build_news.write_patch(None, today)
    assert (third["version"], new) == ("7.41g", False)


def test_without_ukrainian_notes_the_page_shows_the_english_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "PATCHES", tmp_path)
    monkeypatch.setattr(build_news, "fetch_feed", _fake_feed([], ukrainian=False))
    post, _, _ = build_news.write_patch("7.41f", date(2026, 9, 15))
    assert post["languages"]["uk"] == post["languages"]["en"]


def test_the_stored_patches_have_pages():
    for patch in news.load_patches():
        slug = news.patch_slug(patch)
        assert (news.ROOT / "site" / "news" / f"{slug}.html").exists()
        assert (news.ROOT / "site" / "en" / "news" / f"{slug}.html").exists()
        assert set(patch["languages"]) == set(news.FEED_LANGUAGES)
