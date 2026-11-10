# ruff: noqa: S603, S607  — ffmpeg is a fixed argv, not user input.
"""Capture the console. Optional: needs Playwright and ffmpeg, not used by CI.

python3 -m skyline serve --port 8097
python3 scripts/capture_demo.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets"
RAW = ROOT / "build" / "capture"
URL = "http://127.0.0.1:8097"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if RAW.exists():
        shutil.rmtree(RAW)
    RAW.mkdir(parents=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("#metrics strong")
        beats: list[tuple[Path, str]] = []

        def snap(name: str, seconds: str) -> None:
            path = RAW / f"{name}.png"
            page.screenshot(path=str(path))
            beats.append((path, seconds))

        snap("steady", "1.8")
        page.screenshot(path=str(OUT / "skyline-dashboard.png"))
        page.locator("#finops").screenshot(path=str(OUT / "skyline-finops.png"))
        page.locator("#guardrail").screenshot(path=str(OUT / "skyline-guardrail.png"))
        page.get_by_role("button", name="1k / day").click()
        page.wait_for_selector("text=more at this volume")
        snap("trickle", "1.8")
        page.get_by_role("button", name="100k / day").click()
        page.wait_for_selector("text=under the naive path")
        snap("volume", "1.2")
        page.locator("#gate").evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        page.get_by_role("button", name="Open the security group").click()
        page.wait_for_selector("text=0.0.0.0/0")
        snap("opened", "2.4")
        page.locator("#gate").screenshot(path=str(OUT / "skyline-gate.png"))
        browser.close()
    script = RAW / "frames.txt"
    lines = ["ffconcat version 1.0"]
    for path, seconds in beats:
        lines.append(f"file '{path}'")
        lines.append(f"duration {seconds}")
    lines.append(f"file '{beats[-1][0]}'")
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    mp4 = OUT / "skyline-demo.mp4"
    gif = OUT / "skyline-demo.gif"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(script),
            "-an",
            "-vf",
            "fps=10,format=yuv420p",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(mp4),
        ],
        check=True,
        capture_output=True,
    )
    palette = RAW / "palette.png"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(mp4),
            "-vf",
            "fps=5,scale=720:-1:flags=lanczos,palettegen=max_colors=80:stats_mode=diff",
            str(palette),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(mp4),
            "-i",
            str(palette),
            "-lavfi",
            "fps=5,scale=720:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4",
            str(gif),
        ],
        check=True,
        capture_output=True,
    )
    print(f"wrote {mp4} ({mp4.stat().st_size} bytes)")
    print(f"wrote {gif} ({gif.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
