#!/usr/bin/env bash
# Collect the deliverables from a finished master into deliver/ (not committed):
# the MP4, the opening alone (0-7.5 s) and four key frames (start, choice, transformation, final).
set -euo pipefail
cd "$(dirname "$0")/.."
src=${1:-out/film_final.mp4}
mkdir -p deliver
cp "$src" deliver/wardly-next-step-uk-1080x1920-60fps.mp4
# the opening alone (0-7.5 s: the hero, the inventory, the choice, the card), cut from the same master;
# the audio fades over its last 0.25 s so the excerpt does not end on a click
ffmpeg -v error -y -i "$src" -t 7.5 -c:v libx264 -preset slow -crf 14 -pix_fmt yuv420p \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv \
  -af "afade=t=out:st=7.25:d=0.25" -c:a aac -b:a 320k -ar 48000 -movflags +faststart \
  deliver/wardly-next-step-intro-uk-1080x1920-60fps.mp4
grab() { ffmpeg -v error -y -i "$src" -vf "select='eq(n,$1)'" -vframes 1 "deliver/$2.png"; }
rm -f deliver/keyframe-*.png
grab 20 keyframe-1-start-0.33s          # Juggernaut stopped on the hit: Dota in the first second
grab 200 keyframe-2-choice-3.3s          # «ЩО КУПИТИ?»: Black King Bar in focus, Butterfly stepped back
grab 267 keyframe-3-transformation-4.45s # the card opening around the Black King Bar icon
grab 1490 keyframe-4-final-24.8s         # logo, «Wardly», slogan, address
ls -la deliver
