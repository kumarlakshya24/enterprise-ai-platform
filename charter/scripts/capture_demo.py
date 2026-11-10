"""Capture the demo stills, GIF, and MP4 from the running UI.

Requires the server from `make up` and a local Chrome. Not part of `make test`.

    python3 scripts/capture_demo.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets"
BASE = "http://127.0.0.1:8097"
CHROME = "/usr/bin/google-chrome"


def shoot(page, name: str) -> None:
    page.screenshot(path=str(OUT / name), full_page=False)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=CHROME,
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE, wait_until="networkidle")
        page.get_by_text("Residency violation").wait_for()
        shoot(page, "desk.png")

        page.get_by_role("button", name="Block · US model").click()
        page.get_by_text("R-RESIDENCY-EU").first.wait_for()
        page.wait_for_timeout(400)
        shoot(page, "residency-deny.png")

        page.get_by_role("button", name="Control matrix").click()
        page.get_by_text("Data governance and residency").wait_for()
        shoot(page, "control-matrix.png")

        page.get_by_role("button", name="Evidence pack").click()
        page.get_by_text("Planted finding").wait_for()
        shoot(page, "evidence-pack.png")
        page.close()

        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            record_video_dir=str(OUT / "_video"),
            record_video_size={"width": 1280, "height": 800},
        )
        clip = context.new_page()
        clip.goto(BASE, wait_until="networkidle")
        clip.get_by_text("Residency violation").wait_for()
        clip.wait_for_timeout(1200)
        clip.get_by_role("button", name="Block · US model").click()
        clip.get_by_text("R-RESIDENCY-EU").first.wait_for()
        clip.wait_for_timeout(1800)
        clip.get_by_role("button", name="Drop residency file").click()
        clip.get_by_text("R-PERMIT-HOSTED-SUPPORT").first.wait_for()
        clip.wait_for_timeout(1800)
        clip.get_by_role("button", name="Control matrix").click()
        clip.get_by_role("button", name="Gaps").click()
        clip.wait_for_timeout(1600)
        clip.get_by_role("button", name="Evidence pack").click()
        clip.get_by_text("not a legal opinion").wait_for()
        clip.wait_for_timeout(1400)
        clip.close()
        context.close()
        browser.close()

    webm = next((OUT / "_video").glob("*.webm"))
    mp4 = OUT / "charter-demo.mp4"
    gif = OUT / "charter-demo.gif"
    subprocess.check_call(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(webm),
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(mp4),
        ]
    )
    subprocess.check_call(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(webm),
            "-an",
            "-vf",
            "fps=10,scale=960:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=96[p];[s1][p]paletteuse",
            str(gif),
        ]
    )
    print(f"wrote {mp4} ({mp4.stat().st_size} bytes)")
    print(f"wrote {gif} ({gif.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
