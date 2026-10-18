# Replay Demo

Replay demo mode shows the overlay without launching Dota 2.

The demo reads an existing GSI-like JSONL file, sends states to the backend through the normal demo endpoint, and lets the backend produce real advice through the recommender and scheduler.

## Demo Files

Primary demo inputs:

```text
data/match_simulations/replay_gsi_like_match_8843382732_pl_20_30.jsonl
data/match_simulations/replay_gsi_like_match_8843471434_jugg_10_20.jsonl
```

Recommended demo:

- Phantom Lancer 20-30 macro/farming.
- Speed `5`.
- Advice hold `8` seconds.
- Fallback-only for stability.

## Run Demo Playback

```bash
cd backend
source .venv/bin/activate
SIMULATION_USE_LLM=false \
python3 scripts/run_overlay_demo.py \
  --simulation-file ../data/match_simulations/replay_gsi_like_match_8843382732_pl_20_30.jsonl \
  --speed 5 \
  --advice-hold-seconds 8
```

The script prints only newly shown advice events by default. Use `--verbose` for every state.

The helper authenticates using the standalone backend's private credentials file. Launcher demo buttons pass their own credentials and selected port through the child environment. If you choose another port manually, set `DOTA_AI_BACKEND_PORT` consistently for the backend and helper and pass `--backend-url http://127.0.0.1:<port>`. See [LOCAL_API_SECURITY.md](LOCAL_API_SECURITY.md); do not print credentials in demo logs.

## Export Session Summary

```bash
SIMULATION_USE_LLM=false \
python3 scripts/run_overlay_demo.py \
  --simulation-file ../data/match_simulations/replay_gsi_like_match_8843382732_pl_20_30.jsonl \
  --speed 5 \
  --advice-hold-seconds 8 \
  --export-summary simulation_results/demo_session_summary_pl_20_30.md \
  --export-summary-json simulation_results/demo_session_summary_pl_20_30.json
```

Summary endpoint during/after a demo (control Bearer header required, or Swagger Authorize):

```text
GET http://127.0.0.1:8000/demo/session-summary
```

## What The Overlay Should Show

- `DEMO REPLAY MODE`
- hero
- simulated time
- stage
- advice action
- reason
- priority
- source/confidence

## Launcher Presets

The Electron launcher includes demo buttons for:

- Phantom Lancer 20-30 macro
- Juggernaut 10-20 safety

Clean logs are for showing the app. Verbose logs are for debugging.

## Limits

Replay-derived GSI-like states may include missing or inferred fields. The current minimal replay parser does not reconstruct every live GSI signal. Advice therefore avoids claims that require exact enemy positions, exact team readiness, or exact objective context.

## Replay a match recording through the current coach

With «Keep match recordings for a week» on (Settings), every match is saved as
gzip JSON lines (`match_records.py`). `scripts/replay_recording.py` feeds such a
file to the current backend, payload by payload with the recording's own wall
time (a fake clock for the advice scheduler), and prints every distinct overlay
card with its match clock: advice, map hints, the death screen and the Aegis on
the timer strip. Use it before and after a rule change to see what the coach
would say in a real game. Recordings are the player's games: keep them on the
computer, never in the repository.

```bash
cd backend
.venv/bin/python ../scripts/replay_recording.py ~/Wardly-match-....jsonl.gz --from 20:00 \
  --items items.json        # optional: OpenDota /api/constants/items saved once
```
