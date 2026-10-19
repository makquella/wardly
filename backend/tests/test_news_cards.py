"""Telegram picture posts (scripts/news_cards.py, scripts/build_news.py): the
captions fit a photo, the hero of the week follows the meta post, the card is
cut to its size and the post falls back to text without a card."""

from __future__ import annotations

import email
import struct
import sys
import zlib
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import build_news  # noqa: E402 - scripts/build_news.py
import news  # noqa: E402
import news_cards as cards  # noqa: E402


def _post(rows):
    stats = [
        {
            "id": index + 1,
            "localized_name": name,
            "pub_pick_trend": [picks // 7] * 7,
            "pub_win_trend": [wins // 7] * 7,
        }
        for index, (name, picks, wins) in enumerate(rows)
    ]
    post = news.meta_post(stats, date(2026, 10, 12))
    for hero in post["heroes"]:  # made-up ids: give each hero a picture key
        hero["key"] = hero["key"] or hero["name"].lower().replace(" ", "_")
    return post


def _rows():
    rows = [(f"Hero {i}", 7_000, 3_500) for i in range(60)]
    rows[0] = ("Pudge", 70_000, 35_000)
    rows[1] = ("Wraith King", 14_000, 7_840)  # 56 %
    rows[2] = ("Juggernaut", 14_000, 7_560)  # 54 %
    rows[3] = ("Anti-Mage", 1_400, 1_050)  # 75 %, but 1 % of matches
    return rows


def _key(post, name):
    return next(h["key"] for h in post["heroes"] if h["name"] == name)


def test_the_meta_caption_fits_a_photo_and_links_the_post():
    post = _post(_rows())
    data = news.summary(post, None)
    caption = cards.meta_caption(post, data)
    assert cards.visible_length(caption) <= cards.CAPTION_LIMIT
    assert caption.startswith("📊 <b>Мета тижня · 6–12 жовтня</b>")
    assert "Wraith King 56,0 %" in caption
    assert "/news/2026-10-12-meta.html?ref=tg" in caption and caption.endswith("#dota2")
    page = cards.meta_card(post, data, Path("/nonexistent"))
    assert "Wraith King" in page and "6–12 жовтня" in page and "{pill}" not in page


def test_the_hero_of_the_week_is_the_best_regular_pick_not_shown_lately():
    post = _post(_rows())
    site = [
        {"name": "Wraith King", "key": _key(post, "Wraith King")},
        {"name": "Juggernaut", "key": _key(post, "Juggernaut")},
        {"name": "Anti-Mage", "key": _key(post, "Anti-Mage")},
        # The site may name a hero differently from OpenDota: the key decides.
        {"name": "Pudge the Butcher", "key": _key(post, "Pudge")},
    ]
    hero, stats = cards.pick_hero(post, site, [])
    assert hero["name"] == "Wraith King" and round(stats["win"], 2) == 0.56
    hero, _ = cards.pick_hero(post, site, ["Wraith King"])
    assert hero["name"] == "Juggernaut"  # Anti-Mage wins more, but is rarely picked
    hero, _ = cards.pick_hero(post, site, ["Wraith King", "Juggernaut"])
    assert hero["name"] == "Pudge the Butcher"
    hero, _ = cards.pick_hero(post, site, ["Wraith King", "Juggernaut", "Pudge the Butcher"])
    assert hero["name"] == "Anti-Mage"


def test_the_hero_caption_uses_the_site_numbers():
    import build_site as site

    hero = next(h for h in site.heroes() if h["name"] == "Juggernaut")
    facts = cards.hero_facts(hero, site)
    caption = cards.hero_caption(hero, facts, {"win": 0.526, "pick": 0.183})
    assert cards.visible_length(caption) <= cards.CAPTION_LIMIT
    assert caption.startswith("⚔️ <b>Герой тижня: Juggernaut</b>")
    assert "52,6 %" in caption and "Blade Fury" in caption
    assert f"нижче <b>{hero['profile']['low_hp_warning_threshold']} %</b>" in caption
    assert "/heroes/juggernaut.html?ref=tg" in caption
    assert "&#x27;" not in caption  # Telegram needs only <, > and & escaped
    page = cards.hero_card(hero, facts, None, Path("/nonexistent"))
    assert "Juggernaut" in page and "Що підкаже Wardly" in page


def test_a_release_caption_keeps_the_headlines_and_the_links():
    notes = "## Що нового\n\n" + "\n".join(
        f"- **Пункт {i}.** Перше речення. " + "текст " * 40 for i in range(60)
    )
    notes += "\n\n---\n\n**In English:**\n- **English part.** Text"
    points = cards.release_points(notes)
    assert points[0] == ("Пункт 0", "Перше речення.")
    assert all("English" not in head for head, _ in points)
    caption = cards.release_caption("0.56.0", points)
    assert cards.visible_length(caption) <= cards.CAPTION_LIMIT
    assert caption.startswith("🚀 <b>Wardly 0.56.0 вже тут</b>")
    assert "changelog.html?ref=tg#v0.56.0" in caption
    assert caption.endswith("оновиться сама, коли Дота буде закрита.")


def _png(width, height):
    rows = b"".join(b"\x00" + bytes([y]) * (width * 3) for y in range(height))

    def chunk(kind, body):
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def test_the_screenshot_is_cut_to_the_card(tmp_path):
    path = tmp_path / "card.png"
    path.write_bytes(_png(4, 10))
    assert cards.crop_png(path, 6)
    data = path.read_bytes()
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (4, 6)
    idat = data.index(b"IDAT")
    (length,) = struct.unpack(">I", data[idat - 4 : idat])
    rows = zlib.decompress(data[idat + 4 : idat + 4 + length])
    assert len(rows) == 6 * (1 + 4 * 3) and rows[-1] == 5
    assert not cards.crop_png(path, 20)  # never taller than it is


def test_a_card_goes_with_its_caption_and_the_token_stays_out_of_the_output(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:secret")
    monkeypatch.setenv("TELEGRAM_CHANNEL", "@wardlydota")
    sent = []

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"ok": true}'

    def urlopen(request, timeout):
        sent.append(request)
        return Answer()

    monkeypatch.setattr(build_news.urllib.request, "urlopen", urlopen)
    picture = tmp_path / "card.png"
    picture.write_bytes(_png(2, 2))
    build_news.send_photo(picture, "<b>Мета</b> & <i>дані</i>")
    request = sent[0]
    assert request.full_url.endswith("/sendPhoto")
    message = email.message_from_bytes(
        b"Content-Type: " + request.headers["Content-type"].encode() + b"\r\n\r\n" + request.data
    )
    parts = {
        part.get_param("name", header="content-disposition"): part for part in message.get_payload()
    }
    assert parts["chat_id"].get_payload() == "@wardlydota"
    assert parts["caption"].get_payload(decode=True).decode() == "<b>Мета</b> & <i>дані</i>"
    assert parts["parse_mode"].get_payload() == "HTML"
    assert parts["photo"].get_payload(decode=True) == picture.read_bytes()
    assert "secret" not in capsys.readouterr().out


def test_without_a_card_the_post_goes_as_text(monkeypatch):
    calls = []
    monkeypatch.setattr(build_news.cards, "render", lambda page, out: False)
    monkeypatch.setattr(build_news, "send", lambda text: calls.append(("text", text)))
    monkeypatch.setattr(
        build_news, "send_photo", lambda path, caption: calls.append(("photo", caption))
    )
    build_news.publish("<html>", "caption", "the long text post", True, None, "meta")
    assert calls == [("text", "the long text post")]


def test_without_a_browser_there_is_no_card(monkeypatch, tmp_path):
    monkeypatch.setattr(cards, "find_chrome", lambda: None)
    assert not cards.render("<html>", tmp_path / "card.png")
    assert not (tmp_path / "card.png").exists()


def test_a_release_with_a_news_post_links_to_it():
    import news_release

    post = news_release.find("0.57.0")
    assert post and len(post["heroes"]) == 20
    caption = cards.release_caption("0.57.0", [], post)
    assert cards.visible_length(caption) <= cards.CAPTION_LIMIT
    assert "<b>Свій план для 20 керрі</b>" in caption
    assert "/news/2026-10-19-release-0-57-0.html?ref=tg" in caption
    assert "✅ Коли гра вирішується" in caption and "Ursa" in caption
