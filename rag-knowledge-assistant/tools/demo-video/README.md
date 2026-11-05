# Walkthrough video and README GIFs

Generates [`docs/assets/lumen-walkthrough.mp4`](../../docs/assets/lumen-walkthrough.mp4) (5 min, 1080p, captioned)
and the GIFs embedded in the README.

| Footage | Source | How |
|:--|:--|:--|
| Explainer scenes | `scenes.js`, `engine.js`, `scenes.css` | HTML animations rendered frame-by-frame at fixed timestamps, so every render is identical |
| Live UI | `record_ui.mjs` | Playwright drives the real app; frames come from Chrome's screencast. Cursor, highlight and captions are an overlay, and captions that describe results are built from the actual `/ask` responses |

All metrics shown in the scenes are read from `eval_results/latest/summary.json` by `build_data.mjs`; nothing is typed in.

## Regenerate

```bash
make up                                       # the API must be running and healthy on :8000
cd tools/demo-video
node build_data.mjs                           # metrics → data.js
node record_ui.mjs                            # live segments → build/live_*.mp4 (restores the edited policy afterwards)
node render_scenes.mjs                        # explainer scenes → build/scene_*.mp4
node render_scenes.mjs --static-bg arch results   # still-background variants used for GIFs
./assemble.sh                                 # → docs/assets/lumen-walkthrough.mp4
./make_gifs.sh                                # → docs/assets/*.gif
node render_scenes.mjs --preview arch 16      # single-frame PNG while editing a scene
```

Requires Node 18+, Playwright with Chromium, and ffmpeg with libx264. `build/` (≈ 0.5 GB of intermediate clips)
is git-ignored.
