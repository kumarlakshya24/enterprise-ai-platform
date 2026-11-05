# Demo assets

| File | What it is |
|------|------------|
| `compare.png` | Same short prompt under default, cost-saver, latency-first, and quality-first |
| `decision.png` | Default route of that prompt, with the score table |
| `hard-math.png` | Premium is the only model that clears the floor |
| `reject.png` | Hard math under the 100 ms policy, rejected |
| `sensitive.png` | Confidential note pinned to local |
| `fallback.png` | Fast Cheap times out, Balanced accepts |
| `switchboard-demo.mp4` | Those frames, three seconds each, silent |

Regenerate with the API already running, or let the script start it:

```bash
make capture
```

`scripts/capture_ui.mjs` boots `python -m switchboard` on port 8092 if nothing is listening,
opens headless Chrome, waits until `body[data-ready=true]`, and writes PNGs. ffmpeg stitches
the PNGs into the mp4. Both tools are local. The script does not upload anything.

If Chrome or ffmpeg is missing, the PNGs and the video stay as they were last committed.
Do not replace them with a stock URL.
