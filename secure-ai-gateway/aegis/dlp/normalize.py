"""Text normalization that keeps a map back to original offsets.

Attackers (and copy-paste from PDFs) hide PII behind fullwidth digits (`４１１１`), zero-width
characters (`dana\u200b.holloway@...`) and similar tricks. We scan a normalized copy, then map
every finding back to the exact span in the original text so the replacement covers the
hidden characters too.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

ZERO_WIDTH = frozenset({"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\u00ad", "\u180e"})


@dataclass(frozen=True)
class NormalizedText:
    original: str
    text: str
    index_map: tuple[int, ...]  # normalized index -> original index

    def to_original_span(self, start: int, end: int) -> tuple[int, int]:
        if not self.index_map or start >= end:
            return start, end
        o_start = self.index_map[start]
        o_end = self.index_map[end - 1] + 1
        return o_start, o_end

    @property
    def changed(self) -> bool:
        return self.text != self.original


def normalize(text: str) -> NormalizedText:
    if text.isascii():
        return NormalizedText(text, text, tuple(range(len(text))))
    out: list[str] = []
    index_map: list[int] = []
    for i, ch in enumerate(text):
        if ch in ZERO_WIDTH:
            continue
        piece = unicodedata.normalize("NFKC", ch) if ord(ch) > 127 else ch
        for c in piece:
            out.append(c)
            index_map.append(i)
    return NormalizedText(text, "".join(out), tuple(index_map))


def has_zero_width(text: str) -> bool:
    return any(ch in ZERO_WIDTH for ch in text)
