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
    # Without other angles the best win rate leads.
    assert caption.startswith("📊 <b>Anti-Mage") and "75,0 %" in caption.split("\n")[0]
    assert "Wraith King 56,0 %" in caption and "🔥 Беруть: Pudge" in caption
    assert "6–12 жовтня" in caption
    assert "/news/2026-10-12-meta.html?ref=tg" in caption and caption.endswith("#мета_тижня")
    assert "безкоштовний тренер, що підказує" not in caption  # no slogan
    page = cards.meta_card(post, data, Path("/nonexistent"))
    assert "Wraith King" in page and "6–12 жовтня" in page and "{pill}" not in page


def test_the_meta_post_leads_with_the_weeks_angle_and_shows_the_next_two():
    rows = _rows()
    rows[3] = ("Anti-Mage", 700, 525)  # under 2 % of matches: out of the lists
    rows[4] = ("Lion", 50_000, 23_000)  # a top pick under 49 %
    weeks = [_post(rows) for _ in range(3)]
    for week, day in zip(weeks, ("2026-10-12", "2026-10-19", "2026-10-26"), strict=True):
        end = date.fromisoformat(day)
        week["date"], week["to"] = day, day
        week["from"] = date.fromordinal(end.toordinal() - 6).isoformat()
    post = weeks[-1]
    data = news.summary(post, weeks[1])
    angles = news.meta_angles(post, data, weeks, [])
    assert [a["kind"] for a in angles] == ["streak", "trap", "quiet"]
    caption = cards.meta_caption(post, data, angles)
    first = caption.split("\n")[0]
    assert "Wraith King" in first and "3-й тиждень" in first and "56,0 %" in first
    assert "Lion" in caption and "46,0 %" in caption
    assert "0,5 п. п." in caption  # the quiet week says how little moved
    assert cards.meta_caption(post, data, angles) == caption  # the same words when redrawn
    page = cards.meta_card(post, data, Path("/nonexistent"), angles)
    assert "3-й тиждень на вершині" in page and "Популярний, але програє" in page
    assert "Lion" in page and "Виграють" in page


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
    caption = cards.hero_caption(hero, facts, {"win": 0.526, "pick": 0.183}, "2026-10-29")
    assert cards.visible_length(caption) <= cards.CAPTION_LIMIT
    assert caption.startswith("⚔️ <b>Герой тижня: Juggernaut</b>")
    assert "52,6 %" in caption and "/heroes/juggernaut.html?ref=tg" in caption
    # Juggernaut has a plan: the clearest counter record opens, the rest follows once.
    hook = caption.split("\n")[2]
    assert "Monkey King Bar" in hook and "62 %" in hook and "47 %" in hook
    assert caption.count("Monkey King Bar") == 2  # the opening line only, not a bullet too
    assert "• Прокачка: <b>" in caption and "нетворсу на" in caption
    assert "лігові матчі патча" in caption and "Відходьте, коли HP" not in caption
    assert "Керрі — керрі" not in caption
    assert "&#x27;" not in caption  # Telegram needs only <, > and & escaped
    page = cards.hero_card(hero, facts, None, Path("/nonexistent"), "2026-10-29")
    assert "Juggernaut" in page and "Що виграє на цьому герої" in page
    assert '<p class="hook">' in page and "Monkey King Bar" in page
    # A hero without a plan keeps the hero page's thresholds.
    plain = {**facts, "insights": None}
    caption = cards.hero_caption(hero, plain, None)
    assert "Blade Fury" in caption
    assert f"нижче <b>{hero['profile']['low_hp_warning_threshold']} %</b>" in caption
    assert "Що підкаже Wardly" in cards.hero_card(hero, plain, None, Path("/nonexistent"))


def test_a_hero_with_a_plan_comes_before_a_better_win_rate_without_one():
    post = _post(_rows())
    site = [
        {"name": "Wraith King", "key": _key(post, "Wraith King"), "position": "carry"},
        {"name": "Juggernaut", "key": _key(post, "Juggernaut"), "position": "carry"},
    ]
    hero, _ = cards.pick_hero(post, site, [])
    assert hero["name"] == "Juggernaut"  # Wraith King wins more but has no plan
    hero, _ = cards.pick_hero(post, site, ["Juggernaut"])
    assert hero["name"] == "Wraith King"


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


def test_hero_insights_show_only_what_the_plan_and_its_stats_hold():
    import hero_insights

    assert [hero_insights.games_uk(n) for n in (1, 3, 11, 12, 21, 24, 241, 317)] == [
        "1 гра",
        "3 гри",
        "11 ігор",
        "12 ігор",
        "21 гра",
        "24 гри",
        "241 гра",
        "317 ігор",
    ]
    found = hero_insights.facts("Phantom Lancer", "carry")
    assert found["games"] == 317 and found["patch"] == "7.41"
    assert found["skills"]["order"][0] == "Spirit Lance"
    assert found["tempo"]["net_worth"] == 15400 and found["tempo"]["minute"] == 25
    # Only counters with a clear record get numbers; one item and one enemy kind each.
    for counter in found["counters"]:
        record = counter["record"]
        assert record is None or record["with"] - record["without"] >= hero_insights.MIN_GAP
    assert len({c["against"] for c in found["counters"]}) == len(found["counters"])
    kinds = [kind for kind, _title, _sub in hero_insights.rows(found, "en")]
    assert kinds[:3] == ["skills", "tempo", "fast"]
    assert hero_insights.facts("Phantom Lancer", "support") is None
    assert hero_insights.facts("Crystal Maiden", "support") is None
