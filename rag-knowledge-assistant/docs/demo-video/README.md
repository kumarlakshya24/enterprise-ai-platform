# Walkthrough video

`lumen-rag-walkthrough.mp4`: a 5-minute narrated-by-captions tour of the system, 1920×1080, 30 fps.

It interleaves two kinds of footage:

* **Explainer scenes** (`scenes.js`, `engine.js`): HTML animations rendered frame-by-frame at fixed
  timestamps, so every render is identical. All metrics come from `eval_results/latest/summary.json`
  via `build_data.mjs`; nothing is typed in by hand.
* **Live UI footage** (`record_ui.mjs`): the real app at `http://localhost:8000`, driven by Playwright
  and captured with Chrome's screencast. The cursor, highlight box and captions are an overlay; captions
  that describe results are built from the actual `/ask` responses.

## Regenerate

```bash
make up                                   # API, Postgres, Redis must be running and healthy
cd docs/demo-video
node build_data.mjs                       # metrics -> data.js
node record_ui.mjs                        # live segments -> build/live_*.mp4 (restores the edited policy afterwards)
node render_scenes.mjs                    # explainer scenes -> build/scene_*.mp4
./assemble.sh                             # -> lumen-rag-walkthrough.mp4
node render_scenes.mjs --preview arch 16  # single-frame PNG preview while editing a scene
```

Requires Node 18+, Playwright with Chromium, and ffmpeg with libx264. There is no voiceover; the
captions carry the narration.
