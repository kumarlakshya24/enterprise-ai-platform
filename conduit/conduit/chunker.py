"""Chunk redacted text so an erasure boundary does not glue two people together."""

from __future__ import annotations

import hashlib
import re

from conduit.models import Chunk

_PERSON = re.compile(r"\[PERSON:([a-z0-9-]+)\]")
_PARAGRAPHS = re.compile(r"\n\s*\n")


def subjects_in(text: str) -> tuple[str, ...]:
    return tuple(sorted(set(_PERSON.findall(text))))


def content_hash(embed_text: str) -> str:
    return hashlib.sha256(embed_text.encode("utf-8")).hexdigest()


def chunk_document(
    title: str,
    text: str,
    *,
    target_chars: int = 240,
    overlap: int = 0,
) -> list[Chunk]:
    """Pack consecutive paragraphs that share a subject set.

    Paragraphs with different subject sets stay in different chunks, so forgetting
    one person deletes that person's vectors and not the neighbor's paragraph.
    A paragraph longer than `target_chars` is split; `overlap` can widen an
    erasure into the next piece of that same paragraph, which is intentional:
    the vector contains the overlapped tokens.
    """
    if target_chars < 40:
        raise ValueError("target_chars must be at least 40")
    paragraphs = [part.strip() for part in _PARAGRAPHS.split(text) if part.strip()]
    if not paragraphs and text.strip():
        paragraphs = [text.strip()]

    groups: list[dict[str, object]] = []
    for paragraph in paragraphs:
        subjects = frozenset(subjects_in(paragraph))
        current_len = 0
        if groups:
            parts = groups[-1]["parts"]
            assert isinstance(parts, list)
            current_len = sum(len(part) for part in parts) + 2 * max(0, len(parts) - 1)
        if groups and groups[-1]["subjects"] == subjects and current_len + len(paragraph) + 2 <= target_chars:
            parts = groups[-1]["parts"]
            assert isinstance(parts, list)
            parts.append(paragraph)
        else:
            groups.append({"subjects": subjects, "parts": [paragraph]})

    chunks: list[Chunk] = []
    for group in groups:
        parts = group["parts"]
        assert isinstance(parts, list)
        body = "\n\n".join(str(part) for part in parts)
        for piece in _split_oversized(body, target_chars, overlap):
            if piece.strip() == "[erased]":
                continue
            embed_text = f"{title}\n\n{piece}"
            chunks.append(
                Chunk(
                    index=len(chunks),
                    text=piece,
                    embed_text=embed_text,
                    content_hash=content_hash(embed_text),
                    subjects=subjects_in(embed_text),
                )
            )
    return chunks


def _split_oversized(body: str, target_chars: int, overlap: int) -> list[str]:
    if len(body) <= target_chars:
        return [body]
    overlap = max(0, min(overlap, target_chars // 3))
    pieces: list[str] = []
    start = 0
    while start < len(body):
        end = min(len(body), start + target_chars)
        pieces.append(body[start:end])
        if end >= len(body):
            break
        start = end - overlap
    return pieces
