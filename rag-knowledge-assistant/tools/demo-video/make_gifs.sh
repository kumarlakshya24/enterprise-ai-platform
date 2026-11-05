#!/usr/bin/env bash
# Cut short README GIFs from the rendered clips in build/ (run assemble inputs first).
# Each line: name  source-clip  start(s)  duration(s)  speed  width  fps
set -euo pipefail
cd "$(dirname "$0")"
OUT=../../docs/assets
while read -r name src start dur speed width fps; do
  [[ -z "$name" || "$name" == \#* ]] && continue
  f="fps=$fps,setpts=PTS/$speed,scale=$width:-1:flags=lanczos"
  ffmpeg -nostdin -y -loglevel error -ss "$start" -t "$dur" -i "build/$src.mp4" \
    -vf "$f,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
    -loop 0 "$OUT/$name.gif"
  printf '%-14s %s\n' "$name" "$(du -h "$OUT/$name.gif" | cut -f1)"
done <<'SPEC'
architecture  scene_arch_still      3.4  13.4 1.25 960 12
crossteam     live_crossteam   0.3  23.6 1.6  960 10
rbac          live_rbac        0.3  23.8 1.6  960 10
injection     live_injection   4.5  27.4 1.7  960 10
update        live_update      0.3  44.4 2.0  960 10
results       scene_results_still    0.5  12.0 1.2  960 12
SPEC
