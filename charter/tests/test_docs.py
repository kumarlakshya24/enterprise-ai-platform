"""The README embeds the demo and quotes the matrix the code actually computes."""

from __future__ import annotations

from charter.config import ROOT

README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_embeds_gif_and_mp4_near_the_demo() -> None:
    demo_at = README.lower().find("## demo")
    assert demo_at > 0
    demo = README[demo_at : demo_at + 1800]
    assert "docs/assets/charter-demo.gif" in demo
    assert "docs/assets/charter-demo.mp4" in demo
    # GitHub strips <video> tags whose source is a file in the repo, so the README
    # links a poster image to the MP4 instead.
    assert "<video" not in README
    assert "(docs/assets/residency-deny.png)](docs/assets/charter-demo.mp4)" in demo
    assert "<img" in demo
    for name in (
        "charter-demo.gif",
        "charter-demo.mp4",
        "desk.png",
        "residency-deny.png",
        "control-matrix.png",
        "evidence-pack.png",
    ):
        path = ROOT / "docs" / "assets" / name
        assert path.is_file(), name
        assert path.stat().st_size > 1000, name


def test_readme_quotes_the_matrix() -> None:
    assert "10 met" in README
    assert "4 partial" in README
    assert "3 gap" in README
    assert "req-leak-01" in README
    assert "not a legal opinion" in README


def test_architecture_has_two_diagrams_and_the_adrs_exist() -> None:
    architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert architecture.count("```mermaid") >= 2
    adrs = sorted((ROOT / "docs" / "adr").glob("*.md"))
    assert len(adrs) >= 3
    assert (ROOT / "docs" / "FAILURE_MODES.md").is_file()
    assert (ROOT / "docs" / "INTERVIEW_WALKTHROUGH.md").is_file()
