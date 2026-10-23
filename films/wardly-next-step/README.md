# Wardly — «Із хаосу — у наступний крок»

A 25-second vertical promo (1080×1920, 60 fps, Ukrainian voice-over) built in code with
Remotion: typography, the real Wardly UI rebuilt from the app's own CSS and strings, the real logo,
and a soundtrack designed in code. No gameplay footage. Nothing here is published.

- **Idea:** three questions every Dota player asks (*Що купити? Чому відстаю? Що змінити?*)
  collide, stop, and are answered one by one by the product: the live overlay card and the
  post-match review. One clear next step remains.
- **Device:** the question mark's dot. «?» → the full stop of «Купіть.» → the overlay card's status
  dot; the second «?» → the review finding's index «1»; the third → a red dot beside the drill
  (red = *the next step*), the full stop of «крок.», and finally the red dot on the logo's orbit.
- **Grid:** 120 BPM, a beat = 30 frames, a bar = 2 s. `src/timeline.ts` is the only source of time;
  picture, sound cues and the QA gates import it.

Details: [BRIEF.md](BRIEF.md) (spec, sources of every on-screen string, bans and brand exceptions),
[TREATMENT.md](TREATMENT.md) (references, beat sheet, key frames).

## Rebuild

Requirements: Node 22 (`npm install`), Chromium (the sandbox headless shell is found
automatically, or set `REMOTION_BROWSER`), ffmpeg, Python 3.11 with `numpy scipy soundfile
pyloudnorm` (and `opencv-python-headless` for `scripts/forensics.py`).

```bash
cd films/wardly-next-step
npm install
npx tsx audio/export-cues.ts                       # sound cues from the picture's constants -> out/cues.json
python audio/build_soundtrack.py                   # voice + effects + music, mastered -> public/audio/soundtrack.wav
bash scripts/render.sh Film out/film.mp4 --blur    # motion-blurred master + mux + sync/spec gates
# quick check instead of the master:
bash scripts/render.sh Film out/preview.mp4 --preview
```

Gates used on this film:

```bash
npx tsc --noEmit && node scripts/lint-film.mjs src && npx tsx scripts/grid-check.ts src/timeline.ts
bash scripts/layout-audit.sh Film --copy --safe feed9x16
python scripts/probe.py out/film.mp4 --spec 1080x1920@60 --dur 25
python scripts/check-sync.py out/film.mp4 public/audio/soundtrack.wav
python scripts/forensics.py out/film.mp4 --pace crisp --json out/qa/forensics.json
```

Iterate on one part with the `Acts/*` compositions (`npx remotion studio`); `Transition` is the
3.0–10.0 s test of the hardest moment (the storm, the break, the morph into the card).

## Files

| Path | What |
|---|---|
| `src/timeline.ts` | bars, voice placements, cues, every on-screen fragment (`COPY`) |
| `src/data.ts` | the product strings, copied from the codebase, with checks |
| `src/scenes/layout.ts` | geometry: question poses, the cards laid out from the app's CSS numbers, cameras |
| `src/scenes/Chaos.tsx` | the app's numbers in depth, the questions, the «купити → Купіть» roll |
| `src/scenes/Live.tsx` | the word flying into the real overlay card, the card, its status dot |
| `src/scenes/Review.tsx` | the real «Головне на наступну гру» card, the index dot |
| `src/scenes/Finale.tsx` | the slogan, the red dot, the logo's orbit drawing itself, the end card |
| `src/sync.ts`, `audio/export-cues.ts` | sound events computed from the picture's constants |
| `audio/build_soundtrack.py` | effects and music synthesised in numpy, voice placement, ducking, master |
| `audio/vo/` | the six voice takes (`voN.src.mp3` as delivered, `voN.wav` 48 kHz) and `words.json` (word timings) |
| `public/img/` | `logo.png` (= `site/assets/logo.png`), `stage.png` (dithered backdrop, `tools/make_stage.py`) |
| `scripts/` | the cinetic toolkit (MIT, `scripts/LICENSE-cinetic.txt`): render, gates, QA |

## Materials and tools

- Voice: ElevenLabs engine via Higgsfield `text2speech_v2` (`variant: elevenlabs`), preset voice
  "Alexey" (`7c2133e5-68ab-511f-9aed-9a67664382b1`). The repository's own ElevenLabs preset (Alex
  Nekrasov, `eleven_v4`) needs `ELEVENLABS_API_KEY`, which this cloud session did not have.
  Each take was checked with faster-whisper (medium, uk); «чесний розбір» was re-taken as
  «чесний розбір матчу» because the short take was heard as «частний».
- Effects and music: designed in code (no samples, no ElevenLabs SFX: no API key here; Higgsfield
  only offers speech for standalone audio).
- Fonts: Inter and Montserrat (OFL), vendored from `@fontsource-variable`.
- Logo, colours, card markup and strings: this repository (paths in BRIEF.md).
- Icons: lucide `target` and `lightbulb` paths, as vendored in `frontend/launcher/assets/icons/lucide.js` (ISC).
