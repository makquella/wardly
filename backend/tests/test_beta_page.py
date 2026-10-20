"""The beta tester page (scripts/beta_page.py): the four steps name the app's own
buttons and settings, and the heroes are the carries with a plan."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import beta_page  # noqa: E402

RENDERER = ROOT / "frontend" / "launcher" / "renderer"
# Windows SmartScreen's own buttons, not the app's.
WINDOWS = {"Докладніше", "Однаково запустити", "More info", "Run anyway"}


def test_the_heroes_are_the_carry_plans():
    names = beta_page.carries()
    plans = [json.loads(p.read_text(encoding="utf-8")) for p in beta_page.PLANS.glob("*.json")]
    assert names == sorted(p["hero"] for p in plans if "carry" in p.get("positions", []))
    assert len(names) >= 20


def test_every_quoted_label_is_in_the_app():
    app = "".join(
        (RENDERER / name).read_text(encoding="utf-8") for name in ("app-texts.js", "match-texts.js")
    )
    for lang, quotes in (("uk", r"«([^»]+)»"), ("en", r"“([^”]+)”")):
        text = " ".join(line for _, lines in beta_page.TEXT[lang]["steps"] for line in lines)
        labels = {part for label in re.findall(quotes, text) for part in label.split(" → ")}
        assert labels
        missing = [label for label in labels - WINDOWS if f'"{label}"' not in app]
        assert not missing, (lang, missing)


def test_the_page_has_four_steps_heroes_and_links():
    heroes = {"Spectre": {"name": "Spectre", "key": "spectre", "slug": "spectre"}}
    for lang in ("uk", "en"):
        page = beta_page.main(lang, heroes, "", {"spectre"})
        assert page.count('class="beta-step"') == 4
        assert 'href="heroes/spectre.html"' in page and "Ursa" in page
        assert beta_page.DOWNLOAD in page and "js-download" in page
        assert f"{len(beta_page.carries())}" in page
    assert "%2Fen%2Fbeta.html%3Fref%3Dtg-share" in beta_page.main("en", heroes, "../", set())
