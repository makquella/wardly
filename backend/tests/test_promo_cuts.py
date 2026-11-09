"""Wardly Cuts (scripts/promo/cuts.py): the numbers and cards the videos show
come from the data and the app, the timeline keeps the picture and the voice
on one clock, and the sound has a hit for every move. The render itself needs
Chrome and ffmpeg and is not run here."""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.promo import cuts  # noqa: E402


@pytest.fixture(scope="module")
def lanes():
    return cuts.lane_facts()


def _timeline(concept: str, language: str, lanes: dict) -> tuple[list, dict]:
    beats = cuts.beats_for(concept, language, {} if concept == "stun-bkb" else lanes)
    return beats, cuts.arrange(beats, cuts.draft_words(beats))


def test_numbers_are_said_in_words():
    assert cuts.words(87, "uk") == "вісімдесят сім"
    assert cuts.words(15, "uk") == "п'ятнадцять"
    assert cuts.words(87, "en") == "eighty-seven"
    assert cuts.words(40, "en") == "forty"
    assert cuts.percent_words(71, "uk") == "сімдесят один відсоток"
    assert cuts.percent_words(72, "uk") == "сімдесят два відсотки"
    assert cuts.percent_words(55, "uk") == "п'ятдесят п'ять відсотків"
    assert cuts.percent_words(11, "uk") == "одинадцять відсотків"
    assert cuts.thousands_words(54_883, "uk") == "п'ятдесят п'ять тисяч"
    assert cuts.thousands_words(54_883, "en") == "fifty-five thousand"
    assert cuts.plural(15, ("кор", "кори", "корів")) == "корів"
    with pytest.raises(ValueError):
        cuts.words(100, "en")


def test_lane_facts_follow_the_data_and_the_apps_rule(lanes):
    from app import lane_matchup

    files = lane_matchup.load_matchups()
    assert lanes["cores"] == len(files)
    assert lanes["lanes"] == sum(data["lanes"] for data in files.values())
    shares = [entry["pct"] for entry in lanes["top"]]
    assert len(shares) == 5 and shares == sorted(shares, reverse=True)
    by_hero = {data["hero"]: data for data in files.values()}
    for entry in lanes["top"]:
        data = by_hero[entry["hero"]]
        opponent = next(o for o in data["opponents"] if o["hero"] == entry["enemy"])
        # The app itself calls this lane hard, and the share is the file's.
        assert lane_matchup.classify(opponent, data["baseline"]) == "hard"
        assert entry["pct"] == round(100 * opponent["lost"] / opponent["lanes"])
        assert entry["lanes"] >= lane_matchup.MIN_LANES
    first, second, third = lanes["podium"]
    assert first["count"] > second["count"] >= third["count"]
    assert len(lanes["victims"]) == first["count"]
    assert set(lanes["victims"]) <= set(lanes["tiles"])
    hero = lanes["hero"]
    assert hero["name"] == cuts.LANE_HERO and len(hero["hard"]) == 2
    assert hero["hard"][0]["pct"] >= hero["hard"][1]["pct"] > hero["base"]
    assert hero["easy"]["pct"] > hero["base_won"]


def test_the_cards_are_the_apps_own_words(lanes):
    from app.map_hints import TIPS

    for language in cuts.LANGUAGES:
        card = cuts.lane_card(lanes, language)
        hard = lanes["hero"]["hard"][0]
        title, body = TIPS["lane_public_hard"][language]
        assert card["action"] == title.format(hero=hard["hero"])
        assert f"{hard['lost']}" in card["reason"] and f"{hard['lanes']}" in card["reason"]
        assert lanes["hero"]["name"] in card["reason"]
    uk, en = cuts.stun_card("uk"), cuts.stun_card("en")
    assert "Black King Bar" in uk["action"] and uk["label"] == "Терміново"
    assert "Black King Bar" in en["action"] and en["label"] == "Urgent"
    assert uk["reason"] and en["reason"]


@pytest.mark.parametrize("concept", cuts.CONCEPTS)
@pytest.mark.parametrize("language", cuts.LANGUAGES)
def test_the_timeline_keeps_picture_and_voice_on_one_clock(concept, language, lanes):
    beats, timeline = _timeline(concept, language, lanes)
    scenes = timeline["scenes"]
    assert len(scenes) == len(beats) and scenes[0]["start"] == 0
    assert scenes[-1]["type"] == "end"
    said = cuts.narration(beats).split()
    assert [w["w"] for scene in scenes for w in scene["words"]] == said
    for scene, following in zip(scenes, scenes[1:], strict=False):
        assert scene["end"] == following["start"]
    last_end = 0.0
    for scene in scenes:
        assert scene["end"] - scene["start"] >= 0.6
        for word in scene["words"]:
            # Words are said in order and inside their own scene.
            assert word["start"] >= last_end - 0.001
            assert scene["start"] <= word["start"] and word["end"] <= scene["end"] + 0.001
            last_end = word["end"]
        for moment in scene["cues"].values():
            assert scene["start"] <= moment <= scene["end"]
        # Caption lines hold every said word of the scene, in order.
        assert [w["w"] for line in scene["lines"] for w in line["words"]] == [
            w["w"] for w in scene["words"]
        ]
    assert len(timeline["cuts"]) >= len(scenes)
    assert all(cut["to"] > cut["from"] and cut["at"] >= 0 for cut in timeline["cuts"])
    # The pieces of the take never overlap in the take or in the video.
    for cut, following in zip(timeline["cuts"], timeline["cuts"][1:], strict=False):
        assert following["from"] >= cut["to"] - 0.001
        assert following["at"] >= cut["at"] + (cut["to"] - cut["from"]) - 0.001
    assert timeline["total"] == scenes[-1]["end"]
    assert cuts.problems(timeline, None) == []


def test_kinetic_lines_match_the_said_words(lanes):
    """A statement's big lines are what is said: one part per word (or `n` words)."""
    for concept in cuts.CONCEPTS:
        for language in cuts.LANGUAGES:
            beats, _ = _timeline(concept, language, lanes)
            for beat in beats:
                if beat.scene not in ("statement", "grid"):
                    continue
                parts = sum(part.get("n", 1) for line in beat.data["lines"] for part in line)
                assert parts == len(cuts.said(beat)), (concept, language, beat.say)


def test_a_long_pause_in_the_take_is_cut_and_a_beats_own_pause_is_added():
    beats = [
        cuts.Beat("One two.", "statement", {"lines": []}),
        cuts.Beat("Three.", "statement", {"lines": []}, pause=0.5),
        cuts.Beat("Four.", "end", {}),
    ]
    timed = [
        {"word": "One", "start": 0.1, "end": 0.4},
        {"word": "two.", "start": 0.45, "end": 0.8},
        {"word": "Three.", "start": 2.8, "end": 3.2},  # two seconds of silence in the take
        {"word": "Four.", "start": 3.3, "end": 3.7},
    ]
    timeline = cuts.arrange(beats, timed)
    first, second, third = timeline["scenes"]
    # The silence is not kept: the second beat follows within its pause and the lead.
    gap = second["words"][0]["start"] - first["words"][-1]["end"]
    assert 0.5 <= gap <= 0.5 + cuts.MAX_GAP + cuts.LEAD + 0.1
    assert third["end"] == pytest.approx(third["words"][-1]["end"] + cuts.TAIL, abs=0.002)
    assert third["cues"]["site"] < third["words"][-1]["end"]


def test_a_long_pause_inside_a_beat_is_trimmed_without_touching_the_words():
    beats = [
        cuts.Beat("One. Two three.", "statement", {"lines": []}),
        cuts.Beat("Four.", "end", {}),
    ]
    timed = [
        {"word": "One.", "start": 0.1, "end": 0.4},
        {"word": "Two", "start": 1.4, "end": 1.7},  # a second of silence after a full stop
        {"word": "three.", "start": 1.75, "end": 2.1},  # an ordinary gap: kept as it is
        {"word": "Four.", "start": 2.4, "end": 2.8},
    ]
    timeline = cuts.arrange(beats, timed)
    one, two, three = timeline["scenes"][0]["words"]
    assert two["start"] - one["end"] == pytest.approx(cuts.MAX_INNER, abs=0.002)
    assert three["start"] - two["end"] == pytest.approx(0.05, abs=0.002)
    # Every word keeps its own length, and each is inside a piece of the take.
    for word, source in zip([one, two, three], timed, strict=False):
        assert word["end"] - word["start"] == pytest.approx(
            source["end"] - source["start"], abs=0.002
        )
        assert any(
            c["from"] <= source["start"] and source["end"] <= c["to"] for c in timeline["cuts"]
        )
    assert len(timeline["cuts"]) == 3


def test_the_page_holds_the_address_and_only_local_pictures(lanes, tmp_path):
    _, timeline = _timeline("hero-lanes", "en", lanes)
    assets = cuts.assets_for(timeline["scenes"], tmp_path, download=False)
    assert assets["logo"].startswith("file://")
    assert all(key.split(":")[0] in ("logo", "bg", "tile") for key in assets)
    html = cuts.page(timeline, assets, "luhovyimvp.dev/tt", "en", "hero-lanes")
    assert '"site": "luhovyimvp.dev/tt"' in html
    assert "window.renderAt" in html and "__FONTS__" not in html
    # The timeline itself is not changed by adding the address.
    assert "site" not in timeline["scenes"][-1]["data"]


def test_short_addresses_exist_for_every_network():
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_site

    assert set(cuts.NETWORKS) == set(build_site.SHORT_ADDRESSES)
    for name, source in build_site.SHORT_ADDRESSES.items():
        page = build_site.short_pages()[build_site.SITE / name / "index.html"]
        assert f"?ref={source}" in page and 'content="noindex"' in page


def test_publishing_texts(lanes):
    for concept in cuts.CONCEPTS:
        for language in cuts.LANGUAGES:
            text = cuts.publishing(concept, language, {} if concept == "stun-bkb" else lanes)
            assert 10 < len(text["title"]) <= 100
            assert "luhovyimvp.dev" in text["description"] and "#dota2" in text["description"]
            assert "?ref=" not in text["description"]  # a link there cannot be clicked
            assert text["tags"][:3] == ["Dota 2", "dota2", "Wardly"]
    assert lanes["hero"]["name"] in cuts.publishing("hero-lanes", "en", lanes)["title"]


def test_problems_are_named():
    scene = {"type": "statement", "start": 0.0, "end": 50.0}
    end = {"type": "end", "start": 50.0, "end": 52.0}
    found = cuts.problems({"scenes": [scene, end], "total": 52.0}, None)
    assert any("52.0 s" in line for line in found)
    short = {
        "scenes": [
            {"type": "rank", "start": 0.0, "end": 0.3},
            {"type": "end", "start": 0.3, "end": 12.0},
        ],
        "total": 12.0,
    }
    found = cuts.problems(short, {"width": 720, "height": 1280, "audio": False, "seconds": 12.0})
    assert any("shorter than 0.6 s" in line for line in found)
    assert any("end card" in line for line in found)
    assert any("720x1280" in line for line in found) and any("no sound" in line for line in found)


def test_every_voice_of_the_cast_exists():
    assert set(cuts.CAST) == {(c, lang) for c in cuts.CONCEPTS for lang in cuts.LANGUAGES}
    assert set(cuts.CAST.values()) <= set(cuts.VOICES)
    # One voice per video: the eight videos compare eight voices.
    assert len(set(cuts.CAST.values())) == len(cuts.CAST)


def test_the_sound_has_a_hit_for_every_move(lanes, tmp_path):
    pytest.importorskip("numpy")
    from scripts.promo import cuts_sound

    _, timeline = _timeline("lanes-top5", "uk", lanes)
    moves = cuts_sound.events(timeline)
    names = [name.partition(":")[0] for _, name, _ in moves]
    assert names.count("whoosh") >= len(timeline["scenes"]) - 1
    # The last place of the countdown gets the tension and the biggest hit.
    assert "riser" in names and max(gain for _, name, gain in moves if name == "impact") == 1.5
    assert all(-1.2 <= at <= timeline["total"] for at, _, _ in moves)
    for _, name, _ in moves:
        assert len(cuts_sound._sound(name, 1)) > 0
    out = cuts_sound.mix(timeline, None, tmp_path / "sound.wav")
    with wave.open(str(out), "rb") as audio:
        assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (48000, 2, 2)
        assert audio.getnframes() == int(timeline["total"] * 48000)


def test_the_voice_is_cut_and_placed_by_the_timeline(tmp_path):
    np = pytest.importorskip("numpy")
    from scripts.promo import cuts_sound

    take = tmp_path / "take.wav"
    tone = (np.sin(2 * np.pi * 440 * np.arange(48000 * 2) / 48000) * 20000).astype("<i2")
    with wave.open(str(take), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(tone.tobytes())
    track = cuts_sound.voice_track(take, [{"from": 0.5, "to": 1.0, "at": 2.0}], 3.0)
    assert len(track) == 3 * 48000
    assert np.abs(track[: int(1.9 * 48000)]).max() == 0  # nothing before the piece
    assert np.abs(track[int(2.1 * 48000) : int(2.4 * 48000)]).max() > 0.5
    assert np.abs(track[int(2.6 * 48000) :]).max() == 0  # and nothing after it
