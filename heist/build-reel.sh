#!/bin/bash
# Builds a silent scroll-scrub reel from the heist stills.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

names=(vault keeper lookout caser talker clock wheelman alarm ledger pulse)

render() {
  local i="$1"
  local name="$2"
  local expr
  if (( i % 2 == 0 )); then
    expr='min(1+0.0018*on,1.12)'
  else
    expr='max(1.12-0.0018*on,1)'
  fi
  ffmpeg -y -hide_banner -loglevel error -loop 1 -i "$ROOT/$name.jpg" \
    -vf "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,zoompan=z='${expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=70:s=1280x720:fps=25,format=yuv420p" \
    -frames:v 70 -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -an "$TMP/$i.mp4"
}

for i in "${!names[@]}"; do
  render "$i" "${names[$i]}" &
  if (( (i + 1) % 3 == 0 )); then
    wait
  fi
done
wait

cp "$TMP/0.mp4" "$TMP/reel.mp4"
duration=2.8
fade=0.4
for i in 1 2 3 4 5 6 7 8 9; do
  offset=$(python3 -c "print(round($duration - $fade, 3))")
  ffmpeg -y -hide_banner -loglevel error \
    -i "$TMP/reel.mp4" -i "$TMP/$i.mp4" \
    -filter_complex "[0:v][1:v]xfade=transition=fade:duration=${fade}:offset=${offset},format=yuv420p[v]" \
    -map "[v]" -c:v libx264 -preset veryfast -crf 22 -pix_fmt yuv420p -an -movflags +faststart \
    "$TMP/next.mp4"
  mv "$TMP/next.mp4" "$TMP/reel.mp4"
  duration=$(python3 -c "print(round($duration + 2.8 - $fade, 3))")
done

ffmpeg -y -hide_banner -loglevel error -i "$TMP/reel.mp4" \
  -c:v libx264 -preset veryfast -crf 22 -pix_fmt yuv420p \
  -g 12 -keyint_min 12 -sc_threshold 0 -an -movflags +faststart \
  "$ROOT/reel.mp4"
ffprobe -v error -show_entries format=duration,size -of default=nw=1 "$ROOT/reel.mp4"
