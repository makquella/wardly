"""The film «Із хаосу — у наступний крок» (films/wardly-next-step) as a reviewed Shorts package.

beta_campaign=film renders the film in the Promo workflow from its committed sources (Remotion,
the cinetic render with motion blur and its gates) and packs the master here: the MP4, a cover,
its checks and the narration it must contain, which the independent Whisper check reads.
beta_campaign=film-shorts with that run's ID sends the exact reviewed MP4 to the private chat
with the YouTube-only button and its publish time (beta.deliver; beta_shorts.package holds the
title, description and tags). Nothing is published without the owner's press.

    python -m scripts.promo.film --out promo-out --package       # after the film's own render
    python -m scripts.promo.film --out promo-out --speech-check
    python -m scripts.promo.film --out promo-out --send          # beta_campaign=film-shorts
"""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import beta, render

ROOT = Path(__file__).resolve().parents[2]
FILM = ROOT / "films" / "wardly-next-step"
KIND = "wardly-film"
CREATIVE = "next-step"
LANGUAGES = ("uk",)
VISUAL_REVISION = 2  # the Dota opening (Juggernaut, the inventory, the Black King Bar card)
# 17:00 in Kyiv on 24 October 2026 (still summer time, UTC+3, until the 25th).
PUBLISH_AT = "2026-10-24T14:00:00Z"
COVER_AT = 3.3  # «ЩО КУПИТИ?» over Black King Bar and Butterfly: the question the film answers


def voice_lines() -> list[str]:
    """The film's six voice lines, as tools/elevenlabs_vo.py voiced them (one take each)."""
    source = (FILM / "tools" / "elevenlabs_vo.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "TEXTS" for t in node.targets
        ):
            texts = ast.literal_eval(node.value)
            return [texts[n] for n in sorted(texts)]
    raise ValueError("films/wardly-next-step/tools/elevenlabs_vo.py has no TEXTS")


def metadata(language: str = "uk") -> dict[str, Any]:
    """YouTube title, description and tags. Only what the film shows and the app does."""
    if language != "uk":
        raise ValueError("The film is Ukrainian only")
    return {
        "title": "Що купити в Dota 2? Wardly підкаже під час гри",
        "description": (
            "Juggernaut, повний інвентар і одне питання: що купити далі? "
            "Wardly — безкоштовний тренер для Dota 2 на Windows. Під час гри — одна коротка "
            "порада: після двох смертей під контролем він назве Black King Bar і пояснить чому. "
            "Після гри — чесний розбір матчу: де саме ви відстали і що змінити наступного разу.\n\n"
            "Безкоштовно для Windows: https://luhovyimvp.dev/?ref=shorts-next-step-uk\n\n"
            "Без обіцянок приросту MMR: лише ваші матчі й один чіткий наступний крок.\n\n"
            "#Dota2 #ДотаУкраїнською #Juggernaut"
        ),
        "tags": [
            "Dota 2",
            "dota2",
            "Wardly",
            "Дота українською",
            "Juggernaut",
            "Black King Bar",
            "тренер Dota 2",
            "що купити Dota 2",
        ],
    }


def package(out: Path, film: Path | None = None) -> dict[str, Any]:
    """Pack the rendered master (films/wardly-next-step/out/film.mp4) with its checks."""
    film = film or FILM
    master = film / "out" / "film.mp4"
    layout = json.loads((film / "out" / "qa" / "layout-Film.json").read_text(encoding="utf-8"))
    score = json.loads((film / "out" / "qa" / "score.json").read_text(encoding="utf-8"))
    folder = out / "uk"
    folder.mkdir(parents=True, exist_ok=True)
    video = folder / "video.mp4"
    shutil.copyfile(master, video)
    subprocess.run(
        [render.ffmpeg(), "-v", "error", "-y", "-ss", str(COVER_AT), "-i", str(video)]
        + ["-frames:v", "1", "-q:v", "2", str(folder / "cover.jpg")],
        check=True,
    )
    (folder / "script.txt").write_text(" ".join(voice_lines()), encoding="utf-8")
    quality = beta.media_check(video)
    result = {
        "kind": KIND,
        "creative": CREATIVE,
        "language": "uk",
        "draft": False,
        "seconds": round(quality["seconds"], 2),
        "visual_revision": VISUAL_REVISION,
        "layout": {
            "ok": bool(layout.get("pass")),
            "tool": "films/wardly-next-step/scripts/layout-audit.sh",
        },
        "quality": quality,
        "sha256": beta.digest(video),
        "voice_config": {"name": "Alex Nekrasov", "model": "eleven_v4"},
        "soundtrack": {"lufs": score.get("lufs"), "true_peak_db": score.get("true_peak_db")},
    }
    if not result["layout"]["ok"]:
        raise ValueError("The film's layout audit did not pass")
    beta.save(folder / "package.json", result)
    print(f"uk: film {result['seconds']:.2f}s, {result['sha256'][:12]}, layout passed")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("promo-out"))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--package", action="store_true", help="pack the rendered master")
    group.add_argument("--speech-check", action="store_true", help="recognise the narration")
    group.add_argument("--send", action="store_true", help="private chat, YouTube-only button")
    args = parser.parse_args()
    if args.package:
        package(args.out)
    elif args.speech_check:
        beta.speech_check(args.out, LANGUAGES)
    else:
        beta.deliver(args.out, shorts=True, languages=LANGUAGES, kind=KIND)


if __name__ == "__main__":
    main()
