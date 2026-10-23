# The Dota 2 material of the opening, from Valve's own CDN (the one the Wardly app loads its hero
# and item pictures from: frontend/launcher/dota-assets.js). Nothing is redrawn or generated:
#   public/img/dota/juggernaut.webp   the official hero render of dota2.com (videos/dota_react/heroes/
#                                     renders/juggernaut.png, 1440x1440 RGBA), cropped to the figure
#   public/img/dota/items/<key>.png   the item icons (images/dota_react/items/<key>.png, 88x64, the
#                                     game's own size), resampled 4x with Lanczos so the film can
#                                     show them up to ~2.2x without the browser's soft upscale
#   python tools/fetch_dota.py
import io, urllib.request
from pathlib import Path

from PIL import Image

CDN = "https://cdn.cloudflare.steamstatic.com/apps/dota2"
HERO = f"{CDN}/videos/dota_react/heroes/renders/juggernaut.png"
ITEMS = ["power_treads", "bfury", "manta", "magic_wand", "wraith_band", "tpscroll", "black_king_bar", "butterfly"]
OUT = Path(__file__).resolve().parent.parent / "public" / "img" / "dota"
CROP = (120, 60, 1280, 1440)  # the figure (alpha bbox 155,96..1238,1405) with a margin; the film reads this box


def get(url: str) -> Image.Image:
    req = urllib.request.Request(url, headers={"User-Agent": "Wardly promo"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        return Image.open(io.BytesIO(r.read())).convert("RGBA")


def main() -> None:
    (OUT / "items").mkdir(parents=True, exist_ok=True)
    hero = get(HERO)
    assert hero.size == (1440, 1440), hero.size
    hero.crop(CROP).save(OUT / "juggernaut.webp", "WEBP", quality=96, method=6)
    for key in ITEMS:
        icon = get(f"{CDN}/images/dota_react/items/{key}.png")
        assert icon.size == (88, 64), (key, icon.size)
        icon.resize((352, 256), Image.LANCZOS).save(OUT / "items" / f"{key}.png", optimize=True)
    print(f"{OUT}: juggernaut.webp {CROP}, {len(ITEMS)} items")


if __name__ == "__main__":
    main()
