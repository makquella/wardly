"""A release's Telegram post (scripts/news_telegram.py): its own words for players,
never the changelog's headlines; a fix without a post is not posted."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import build_news  # noqa: E402 - scripts/build_news.py
import news_cards as cards  # noqa: E402
import news_release  # noqa: E402
import news_telegram  # noqa: E402


def _post(**change):
    post = {
        "version": "0.70.0",
        "headline": "Wardly 0.70: нова підказка",
        "text": "Перший абзац.\n\n**Жирне.** *Курсив* і [сайт](https://luhovyimvp.dev/) & <теги>.",
    }
    return {**post, **change}


def test_the_text_becomes_telegram_html_with_only_the_needed_escapes():
    html = news_telegram.markup(_post()["text"])
    assert "<b>Жирне.</b>" in html and "<i>Курсив</i>" in html
    assert '<a href="https://luhovyimvp.dev/">сайт</a>' in html
    assert "&amp; &lt;теги&gt;" in html and "&#x27;" not in html
    # A star inside a word or a hashtag's underscore stays as it is.
    assert news_telegram.markup("2*3*4 #герой_тижня") == "2*3*4 #герой_тижня"


def test_the_caption_is_the_posts_words_and_one_line_of_links():
    caption = news_telegram.caption(_post())
    lines = caption.split("\n")
    assert lines[0] == "<b>Wardly 0.70: нова підказка</b>" and lines[2] == "Перший абзац."
    assert "changelog.html?ref=tg#v0.70.0" in caption and "/?ref=tg" in caption
    assert "✅" not in caption and "Що нового" not in caption
    with_page = news_telegram.caption(_post(), news_release.find("0.57.0"))
    assert "/news/2026-10-19-release-0-57-0.html?ref=tg" in with_page


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"headline": ""}, "headline"),
        ({"headline": "x" * 80}, "fit the card"),
        ({"text": "x" * 1000}, "Telegram allows"),
        ({"example": {"title": "Фарм зараз"}}, "example"),
        ({"scene": "../../etc/passwd"}, "scene"),
        ({"scene": "nowhere"}, "scene"),
        ({"emoji": "🚀"}, "unknown fields"),
        ({"text": "[тут](https://example.com)"}, "links"),
    ],
)
def test_a_post_that_would_not_fit_or_render_is_refused(change, problem):
    assert any(problem in p for p in news_telegram.validate(_post(**change), "0.70.0"))


def test_the_written_posts_are_ready():
    for path in sorted(news_telegram.POSTS.glob("*.json")):
        post = news_telegram.load(path.stem)
        assert news_telegram.validate(post, path.stem) == [], path.name


def test_the_release_card_shows_the_promise_and_the_hint_not_a_checklist():
    post = news_telegram.load("0.61.0")
    assert post is not None
    page = cards.release_card(post)
    assert "Оновлення 0.61" in page and "Підкаже, куди йти фармити" in page
    assert "Фарм зараз: хвиля на нижній лінії" in page and "game/forest.jpg" in page
    assert "Перевірка" not in page and "{pill}" not in page
    plain = cards.release_card({**post, "example": None})
    assert "review.jpg" in plain


def _run(monkeypatch, *argv):
    published = []
    monkeypatch.setattr(sys, "argv", ["build_news.py", *argv])
    monkeypatch.setattr(build_news, "publish", lambda *args: published.append(args))
    return build_news.main(), published


def test_a_release_is_posted_only_with_its_own_post(monkeypatch, capsys):
    code, published = _run(monkeypatch, "telegram-release", "0.61.0")
    assert code == 0 and len(published) == 1
    card, caption, fallback, *_ = published[0]
    assert caption == fallback and caption.startswith("<b>Wardly 0.61: підкаже")
    # Not the changelog's bold headlines («Фарм зараз», «Перевірка»…) as a list.
    assert "✅" not in caption and "<b>Перевірка" not in caption
    assert "<b>Лише те, що видно" not in caption and "<b>Фарм зараз" not in caption

    code, published = _run(monkeypatch, "telegram-release", "0.60.2")
    assert code == 0 and published == []
    assert "fix with no Telegram post: skipped" in capsys.readouterr().out

    # A minor release without its post (the version check stops that before a
    # release): never the changelog's headlines in its place.
    code, published = _run(monkeypatch, "telegram-release", "0.59.0")
    assert code == 0 and published == []
    assert "::warning::" in capsys.readouterr().out


def test_a_broken_post_stops_the_release_post(monkeypatch, tmp_path):
    monkeypatch.setattr(news_telegram, "POSTS", tmp_path)
    (tmp_path / "0.70.0.json").write_text('{"version": "0.70.0"}', encoding="utf-8")
    with pytest.raises(SystemExit, match="not ready"):
        _run(monkeypatch, "telegram-release", "0.70.0")
