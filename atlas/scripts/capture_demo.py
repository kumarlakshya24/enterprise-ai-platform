"""Capture the kill-and-resume UI. Requires the demo server on :8095 and Chrome."""

from __future__ import annotations

import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets"
RAW = ROOT / "docs" / "demo-video" / "raw"
URL = "http://127.0.0.1:8095/"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(RAW),
            record_video_size={"width": 1280, "height": 720},
        )
        page = context.new_page()
        page.goto(URL, wait_until="networkidle")
        page.wait_for_function("document.querySelector('#workflow').options.length > 0")
        page.select_option("#workflow", "refund")
        page.select_option("#crash", "post_ledger:after_remote")
        page.wait_for_timeout(600)
        page.screenshot(path=str(OUT / "01-start.png"))
        page.click("#start")
        page.wait_for_selector("#status-pill:has-text('paused_approval')")
        page.wait_for_timeout(1800)
        page.screenshot(path=str(OUT / "02-approval.png"))
        page.click("#approve")
        page.wait_for_function("document.querySelector('#ledger-count').textContent === '1'")
        page.wait_for_selector("#banner", state="visible")
        page.wait_for_timeout(2000)
        page.screenshot(path=str(OUT / "03-crashed-after-ledger.png"))
        page.click("#resume")
        page.wait_for_selector("#status-pill:has-text('completed')")
        page.wait_for_function("document.querySelector('#email-count').textContent === '1'")
        page.wait_for_function("document.querySelector('#ledger-count').textContent === '1'")
        page.wait_for_timeout(2000)
        page.screenshot(path=str(OUT / "04-resumed-one-debit.png"))
        page.click("#baseline")
        page.wait_for_selector("#baseline-note:not(.hidden)")
        page.wait_for_timeout(1600)
        page.screenshot(path=str(OUT / "05-baseline-double-debit.png"))
        page.select_option("#crash", "")
        page.select_option("#fault", "email-permanent")
        page.click("#start")
        page.wait_for_selector("#status-pill:has-text('paused_approval')")
        page.click("#approve")
        page.wait_for_selector("#status-pill:has-text('compensated')")
        page.wait_for_function("document.querySelector('#credit-count').textContent === '1'")
        page.wait_for_timeout(1400)
        page.screenshot(path=str(OUT / "06-compensated.png"))
        video = page.video
        page.close()
        context.close()
        browser.close()
        webm = Path(video.path())
    mp4 = OUT / "atlas-kill-resume.mp4"
    subprocess.check_call(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(webm),
            "-an",
            "-vf",
            "scale=1280:720,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-movflags",
            "+faststart",
            str(mp4),
        ]
    )
    gif = OUT / "atlas-kill-resume.gif"
    subprocess.check_call(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(mp4),
            "-vf",
            "fps=8,scale=800:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse",
            "-loop",
            "0",
            str(gif),
        ]
    )
    print(f"mp4 {mp4} {mp4.stat().st_size}")
    print(f"gif {gif} {gif.stat().st_size}")


if __name__ == "__main__":
    main()
