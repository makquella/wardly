#!/usr/bin/env bash
# Collect the deliverables from a finished master into deliver/ (not committed):
# the MP4, the three key frames (start, transformation, final) and a poster.
set -euo pipefail
cd "$(dirname "$0")/.."
src=${1:-out/film.mp4}
mkdir -p deliver
cp "$src" deliver/wardly-next-step-uk-1080x1920-60fps.mp4
grab() { ffmpeg -v error -y -i "$src" -vf "select='eq(n,$1)'" -vframes 1 "deliver/$2.png"; }
grab 216 keyframe-1-start-3.6s          # the three questions colliding over the app's numbers
grab 352 keyframe-2-transformation-5.9s # «Купіть.» on its way into the real overlay card
grab 1490 keyframe-3-final-24.8s        # logo, «Wardly», slogan, address
ls -la deliver
