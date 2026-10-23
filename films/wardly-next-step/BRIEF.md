# Brief — «Із хаосу — у наступний крок»

**Spec:** 1080x1920@60, 25.0 s (1500 f), 120 BPM (30 f beat, 120 f bar), pace: crisp hook → calm body,
audio: Ukrainian VO (ElevenLabs `eleven_v4`, Alex Nekrasov, the repository preset) + ElevenLabs SFX and
music bed (three parts on the grid), master −14 LUFS, true peak ≤ −1.5 dBTP.

- **Product:** Wardly — free, local-first Dota 2 coach for Windows: a short card over the game while
  you play, an honest review after it (README, site).
- **Audience:** Dota 2 players, Ukrainian. Shown in vertical feeds (Shorts/Reels/TikTok): text stays
  inside the `feed9x16` safe zone (top 270, right 120, bottom 420, left 64).
- **Message:** from too much information to one clear next step.
- **No gameplay footage.** Typography, the real Wardly UI (rebuilt from the app's CSS and texts),
  the real logo, sound.

## What may be shown (verified in the repo)

| On screen | Source |
|---|---|
| Death-screen card: «Відродження через 23 с» / «Купіть Black King Bar зараз: золота вистачає, кур'єр принесе.» / the Black King Bar icon / «Чому Black King Bar: смертей під контролем — 2, з ним контроль вас не втримає.» | `backend/app/death_screen.py` (`TEXT.uk`: `title`, `buy_item`, `why_disabled`; the item icon `card["items"]`), the item from `situational_items.py` (two deaths held by stuns); layout `frontend/launcher/overlay/app.js:showDeathScreen` + `overlay/styles.css` (`.death-screen` red stripe, `.plan .action` 14 px, `.items-row` 32×24) |
| Juggernaut, item icons (Power Treads, Battle Fury, Manta Style, Magic Wand, Wraith Band, TP Scroll; Butterfly, Black King Bar) | Valve's CDN (`tools/fetch_dota.py`), the source the app itself uses (`frontend/launcher/dota-assets.js`); the inventory is Juggernaut's own plan (`data/heroes/item_plans/juggernaut.json`), Butterfly its next damage item |
| «Головне на наступну гру» → «Програли лінію за добиваннями» · «Лінія» · «36 добивань до 10:00 проти 65 у керрі у цьому матчі (Anti-Mage).» · «Вправа: На лінії стежте за HP кріпів…» | `analysis_texts.FINDINGS["peer_lh10_behind"]`, `SECTIONS`, `PEER_ROLES`; labels `renderer/match-texts.js` (`focusTitle`, `drill`); markup `renderer/matches.js:focusCard/findingItem`; numbers from the app's own demo review (`site/assets/app/uk/review-ai.jpg`) |
| Logo, colours, fonts | `site/assets/logo.png`, `frontend/launcher/assets/ui/tokens.css`, Montserrat + Inter (site/app) |
| CTA `luhovyimvp.dev`, «Безкоштовно для Windows» | README, site root (`<html lang="uk">`, checked live 2026-10-23) |

Not claimed: MMR gains, statistics about users, hidden-enemy knowledge, anything the app does not do.

## Hard bans (cinetic) and brand-supplied exceptions

No eyebrow labels, no "Introducing", no text walls or filler text, no serif/italic, no orange/amber/
beige/cream/neon/purple/multi-hue gradients/glassmorphism as *film* colours, no emoji/stock icons,
particles, lens flares, glitch presets, bouncy overshoot on copy.

Brand-supplied exceptions (the real product, reproduced exactly):
- the logo's cream eye (`#efe5d4` in `logo.png`) — brand-supplied;
- the overlay's red death-screen stripe (`--error #eb6f6f`) and the amber/cream tokens — product UI;
- Valve's Dota 2 art (the Juggernaut render's oranges and yellows, the item icons) and the inventory's
  slot greys — the game's own material, not film colours;
- the lucide `target` / `lightbulb` icons are the app's own UI icons, not decoration.

The film's own accent is the logo red (`#f05560` text / `#d23a46` fill). Meaning: **the next step**.
It appears only when an answer turns into an action (the drill marker, the final dot, the logo).
