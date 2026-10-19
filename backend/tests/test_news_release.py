"""A Wardly release as a news post (scripts/news_release.py): one page per file in
data/news/releases, in the news list with the other posts, both languages."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import news_release  # noqa: E402


def _post():
    return {
        "date": "2026-10-19",
        "version": "0.57.0",
        "heroes": ["Spectre", "Not On The Site"],
        "games": 10451,
        **{
            lang: {
                "title": f"Wardly 0.57: {lang}",
                "lead": "Перше речення. Друге.",
                "tiles": {"heroes": "h", "games": "g", "patch": "p"},
                "sections": [{"heading": "Розділ", "hint": "Підказка", "items": ["Пункт <1>"]}],
                "heroes_title": "Герої",
                "heroes_hint": "Ще будуть.",
                "changelog": "Усі зміни",
                "share_text": "Поділіться",
                "badge": "Wardly",
            }
            for lang in ("uk", "en")
        },
    }


def test_every_release_file_has_both_languages():
    posts = news_release.load_releases()
    assert posts, "data/news/releases is empty"
    for post in posts:
        for lang in ("uk", "en"):
            assert post[lang]["title"] and post[lang]["sections"]
            assert all(s["items"] for s in post[lang]["sections"])


def test_the_page_lists_sections_heroes_and_links(tmp_path, monkeypatch):
    (tmp_path / "2026-10-19-0.57.0.json").write_text(json.dumps(_post()), encoding="utf-8")
    monkeypatch.setattr(news_release, "RELEASES", tmp_path)
    post = news_release.find("0.57.0")
    assert news_release.slug(post) == "2026-10-19-release-0-57-0"
    heroes = {"Spectre": {"name": "Spectre", "key": "spectre", "slug": "spectre"}}
    page = news_release.post_main(post, "uk", heroes, "../", "../", {"spectre"})
    assert "Пункт &lt;1&gt;" in page
    assert 'href="../heroes/spectre.html"' in page and "Not On The Site" in page
    assert 'href="../changelog.html#v0.57.0"' in page
    assert "10 451" in page
    assert "10,451" in news_release.post_main(post, "en", heroes, "../", "../../")
    item = news_release.list_item(post, "en")
    assert 'href="news/2026-10-19-release-0-57-0.html"' in item and "Перше речення." in item
    assert news_release.find("9.9.9") is None
