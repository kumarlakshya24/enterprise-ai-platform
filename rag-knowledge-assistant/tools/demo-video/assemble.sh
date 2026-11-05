#!/usr/bin/env bash
# Concatenate explainer scenes and live UI clips (story order) into the final walkthrough video.
set -euo pipefail
cd "$(dirname "$0")/build"
ORDER=(scene_title scene_problem scene_arch live_laptop scene_chunk scene_funnel live_crossteam
       scene_security live_rbac live_injection live_refusal scene_incremental scene_cache live_update
       scene_results live_evaltab scene_honest scene_outro)
: > concat.txt
for c in "${ORDER[@]}"; do [ -f "$c.mp4" ] || { echo "missing $c.mp4"; exit 1; }; echo "file '$c.mp4'" >> concat.txt; done
ffmpeg -y -loglevel error -f concat -safe 0 -i concat.txt -f lavfi -i anullsrc=r=48000:cl=stereo \
  -map 0:v -map 1:a -shortest -vf "fps=30,format=yuv420p" -c:v libx264 -preset slow -crf 20 \
  -c:a aac -b:a 96k -movflags +faststart ../../../docs/assets/lumen-walkthrough.mp4
ffprobe -v error -show_entries format=duration,size -of default=nw=1 ../../../docs/assets/lumen-walkthrough.mp4
