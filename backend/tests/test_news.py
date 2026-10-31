"""The weekly meta post (scripts/news.py, scripts/build_news.py): numbers from
OpenDota's public hero statistics, the same lists on the site and in Telegram."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import news  # noqa: E402 - scripts/news.py


def _stats(rows):
    return [
        {
            "id": index + 1,
            "localized_name": name,
            "pub_pick_trend": [picks // 7] * 7,
            "pub_win_trend": [wins // 7] * 7,
        }
        for index, (name, picks, wins) in enumerate(rows)
    ]


def _rows(top_win=0.56):
    rows = [(f"Hero {i}", 7_000, 3_500) for i in range(60)]
    rows[0] = ("Pudge", 70_000, 35_000)
    rows[1] = ("Wraith King", 14_000, int(14_000 * top_win))
    rows[2] = ("Rare Pick", 700, 630)  # wins 90 % of a handful of games
    return rows


def test_a_post_keeps_each_heros_week_and_the_lists_follow_the_numbers():
    post = news.meta_post(_stats(_rows()), date(2026, 10, 12))
    assert post["date"] == "2026-10-12" and post["from"] == "2026-10-06"
    assert {hero["name"] for hero in post["heroes"]} >= {"Pudge", "Wraith King"}
    data = news.summary(post, None)
    assert data["win"][0]["name"] == "Wraith King"
    assert "Rare Pick" not in {row["name"] for row in data["win"]}  # under 2 % of matches
    assert data["pick"][0]["name"] == "Pudge"
    # No earlier post and an even week: nobody rose or fell, so the lead does not say so.
    assert data["up"] == [] and data["down"] == [] and data["moves"] is None
    assert "змінився" not in news.lead(post, data, "uk")
    with pytest.raises(ValueError):
        news.meta_post(_stats(_rows()[:10]), date(2026, 10, 12))  # a broken answer


def test_movers_inside_the_week_when_there_is_no_earlier_post():
    stats = _stats(_rows())
    for row in stats:
        if row["localized_name"] == "Wraith King":
            # 50 % of 2000 a day in the first half, 60 % in the second.
            row["pub_pick_trend"] = [2000] * 7
            row["pub_win_trend"] = [1000, 1000, 1000, 1100, 1200, 1200, 1200]
    post = news.meta_post(stats, date(2026, 10, 12))
    data = news.summary(post, None)
    assert data["moves"] == "inside"
    assert [row["name"] for row in data["up"]] == ["Wraith King"]
    assert data["up"][0]["change"] == pytest.approx(10.0, abs=0.1)
    assert "змінився за тиждень" in news.lead(post, data, "uk")
    page = news.post_main(post, data, "uk", {}, "../", "../", {"skeleton_king"})
    assert "Ростуть" in page and "Падають" not in page
    assert "першими трьома днями тижня" in page
    assert 'src="../assets/heroes/' in page or "hero-pic-none" in page


def test_movers_against_the_previous_post():
    before = news.meta_post(_stats(_rows(0.50)), date(2026, 10, 5))
    after = news.meta_post(_stats(_rows(0.56)), date(2026, 10, 12))
    assert news.previous_of(after, [after, before]) is before
    data = news.summary(after, before)
    assert data["moves"] == "week"
    assert [row["name"] for row in data["up"]] == ["Wraith King"]
    assert data["up"][0]["change"] == pytest.approx(6.0, abs=0.1)
    assert data["down"] == []


def test_texts_in_both_languages():
    post = news.meta_post(_stats(_rows()), date(2026, 10, 12))
    data = news.summary(post, None)
    assert news.title(post, "uk") == "Мета тижня: 6–12 жовтня"
    assert news.title(post, "en") == "Meta of the week: 6–12 October"
    assert news.percent(0.551, "uk") == "55,1 %" and news.percent(0.551, "en") == "55.1%"
    assert news.points(-1.24, "uk") == "−1,2 п. п."
    page = news.post_main(post, data, "uk", {"Pudge": "pudge"}, "../", "../", set())
    assert '<a href="../heroes/pudge.html">Pudge</a>' in page
    assert "t.me/share/url?" in page and "t.me/wardlydota" in page
    # Without a picture the hero gets their initials.
    assert 'hero-pic-none" aria-hidden="true">WK<' in page
    assert news.long_date("2026-10-12", "uk") == "12 жовтня 2026"


def test_an_overlapping_or_old_post_is_not_the_previous_week():
    stats = _stats(_rows(0.50))
    early = news.meta_post(stats, date(2026, 10, 10))  # 4-10 October
    monday = news.meta_post(_stats(_rows(0.56)), date(2026, 10, 12))  # 6-12 October
    # Five shared days: not «against the previous week», the week's own halves instead.
    assert news.summary(monday, early)["moves"] != "week"
    week_later = news.meta_post(_stats(_rows(0.56)), date(2026, 10, 17))  # 11-17 October
    assert news.summary(week_later, early)["moves"] == "week"
    month_later = news.meta_post(_stats(_rows(0.56)), date(2026, 11, 10))
    assert news.summary(month_later, early)["moves"] != "week"


def test_meta_angles_a_patch_move_a_pick_shift_and_a_quiet_strong_pick():
    before_rows, after_rows = _rows(0.50), _rows(0.56)  # Wraith King +6 points
    before_rows[3] = ("Gem", 2_000, 1_000)
    after_rows[3] = ("Gem", 2_000, 1_100)  # 55 %, about 4 % of matches
    after_rows[10] = ("Hero 10", 14_000, 7_000)  # picked twice as often
    before = news.meta_post(_stats(before_rows), date(2026, 10, 5))
    after = news.meta_post(_stats(after_rows), date(2026, 10, 12))
    data = news.summary(after, before)
    patch = {"version": "7.41g", "date": "2026-10-08"}
    patch["languages"] = {"en": {"heroes": [{"name": "Wraith King"}]}}
    angles = news.meta_angles(after, data, [after, before], [patch])
    assert [(a["kind"], a["row"]["name"]) for a in angles] == [
        ("patch_rise", "Wraith King"),
        ("picked_more", "Hero 10"),
        ("gem", "Gem"),
    ]
    assert angles[0]["patch"] == "7.41g" and angles[0]["basis"] == "week"
    assert angles[1]["change"] == pytest.approx(14.2, abs=0.1)
    # A patch from over three weeks before is old news: the move is a plain rise.
    old = {**patch, "date": "2026-09-01"}
    kinds = [a["kind"] for a in news.meta_angles(after, data, [after, before], [old])]
    assert kinds[0] == "picked_more" and "rise" in kinds and "patch_rise" not in kinds


def test_a_streak_skips_an_overlapping_post_and_ends_at_a_gap():
    rows = _rows()
    first = news.meta_post(_stats(rows), date(2026, 10, 5))  # 29 September - 5 October
    overlapping = news.meta_post(_stats(rows), date(2026, 10, 8))
    second = news.meta_post(_stats(rows), date(2026, 10, 12))
    assert news.win_streak(second, [second, overlapping, first]) == 2
    late = news.meta_post(_stats(rows), date(2026, 10, 30))
    assert news.win_streak(late, [late, second, first]) == 1  # over a week apart


def test_the_channel_voice_is_stable_for_a_seed_and_varies_between_seeds():
    import string

    import news_voice

    line = news_voice.say("top", "2026-10-12", hero="Wraith King", win="56,0 %")
    assert line == news_voice.say("top", "2026-10-12", hero="Wraith King", win="56,0 %")
    assert "Wraith King" in line and "56,0 %" in line
    seen = {news_voice.pick(news_voice.LINES["streak"], str(day)) for day in range(40)}
    assert len(seen) == len(news_voice.LINES["streak"])
    # Every variant uses only the values its caller passes (news_cards.py).
    meta = {"hero", "win", "pick", "weeks", "patch", "when", "min", "delta"}
    passed = {
        "hero_counter": {"hero", "item", "against", "with_", "without"},
        "hero_skills": {"hero", "top", "win", "first", "alt"},
        "hero_tempo": {"hero", "net_worth", "minute", "win"},
        "hero_plain": {"hero", "win", "pick"},
        "patch_head": {"version"},
    }
    for kind, variants in news_voice.LINES.items():
        allowed = passed.get(kind, set() if "cta" in kind or kind == "patch_most" else meta)
        for variant in variants:
            fields = {name for _, name, _, _ in string.Formatter().parse(variant) if name}
            assert fields <= allowed, (kind, variant)
