#!/usr/bin/env python3
"""Check markdown links and images in the project READMEs.

Relative links, images, GIF and MP4 paths must resolve to a git-tracked file
(or a directory that contains one). Same-file and cross-file heading anchors
are checked with GitHub's slug rules. A GitHub Actions badge or workflow URL
must name a file under .github/workflows/.

Usage:
    python scripts/check_docs.py
    python scripts/check_docs.py README.md atlas/README.md
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_FILES = (
    "README.md",
    "secure-ai-gateway/README.md",
    "rag-knowledge-assistant/README.md",
    "switchboard/README.md",
    "forge/README.md",
    "atlas/README.md",
    "lens/README.md",
    "charter/README.md",
)

# github-slugger punctuation class, plus the emoji this repo puts in headings.
# Emoji are removed and the following space is left in place, which is why
# "## 🗺️ Title" slugs to "-title" on GitHub.
_PUNCT = re.compile(r"[\u2000-\u206F\u2E00-\u2E7F\\'\"!#$%&()*+,./:;<=>?@\[\]^`{|}~]")
_EMOJI = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0000FE0F"
    "\U0000200D"
    "\U0000200B"
    "]+",
    flags=re.UNICODE,
)
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^(`{3,}|~{3,})")
_MD_LINK = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)|\[([^\]]+)\]\(([^)]+)\)")
_HTML_ATTR = re.compile(
    r"""(?:src|href|poster)\s*=\s*(?:"([^"]+)"|'([^']+)')""",
    re.IGNORECASE,
)
_WORKFLOW_URL = re.compile(
    r"^https://github\.com/kumarlakshya24/personal-projects/actions/workflows/"
    r"(?P<name>[A-Za-z0-9._-]+\.ya?ml)(?:/badge\.svg)?/?$"
)
_SKIP_SCHEMES = ("http://", "https://", "mailto:", "data:")


def github_slug(text: str) -> str:
    text = _EMOJI.sub("", text.lower())
    text = _PUNCT.sub("", text)
    return text.replace(" ", "-")


def tracked_paths() -> set[str]:
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    return {line for line in out.splitlines() if line}


def _blank_keep_newlines(match: re.Match[str]) -> str:
    return re.sub(r"[^\n]", "", match.group(0))


def strip_fenced(text: str) -> str:
    """Blank fenced code and HTML comments without shifting line numbers."""
    lines: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        newline = "\n" if line.endswith("\n") else ""
        match = _FENCE.match(line)
        if fence is None and match:
            fence = match.group(1)[0]
            lines.append(newline)
            continue
        if fence is not None:
            if line.startswith(fence * 3):
                fence = None
            lines.append(newline)
            continue
        lines.append(line)
    body = "".join(lines)
    return re.sub(r"<!--.*?-->", _blank_keep_newlines, body, flags=re.S)


def headings(text: str) -> set[str]:
    found: dict[str, int] = {}
    slugs: set[str] = set()
    fence: str | None = None
    for line in text.splitlines():
        match = _FENCE.match(line)
        if fence is None and match:
            fence = match.group(1)[0]
            continue
        if fence is not None:
            if line.startswith(fence * 3):
                fence = None
            continue
        heading = _HEADING.match(line)
        if not heading:
            continue
        slug = github_slug(heading.group(2))
        count = found.get(slug, 0)
        found[slug] = count + 1
        slugs.add(slug if count == 0 else f"{slug}-{count}")
    return slugs


def destinations(text: str) -> list[tuple[int, str]]:
    visible = strip_fenced(text)
    found: list[tuple[int, str]] = []
    for lineno, line in enumerate(visible.splitlines(), start=1):
        for match in _MD_LINK.finditer(line):
            dest = match.group(2) or match.group(4)
            found.append((lineno, dest.strip()))
        for match in _HTML_ATTR.finditer(line):
            found.append((lineno, (match.group(1) or match.group(2)).strip()))
    return found


def split_dest(dest: str) -> tuple[str, str]:
    dest = dest.split(" ", 1)[0].strip()
    if dest.startswith("<") and dest.endswith(">"):
        dest = dest[1:-1]
    path, _, fragment = dest.partition("#")
    path = path.split("?", 1)[0]
    return path, fragment


def check_file(rel: str, tracked: set[str]) -> tuple[list[str], int]:
    path = ROOT / rel
    if not path.is_file():
        return [f"{rel}: file not found"], 0
    text = path.read_text(encoding="utf-8")
    own_slugs = headings(text)
    slug_cache: dict[str, set[str]] = {rel: own_slugs}
    errors: list[str] = []
    seen = 0
    for lineno, dest in destinations(text):
        if not dest or dest.startswith("#") and "/" not in dest.split("#", 1)[0]:
            target, fragment = split_dest(dest)
            if dest.startswith("#"):
                seen += 1
                fragment = dest[1:]
                if fragment and fragment not in own_slugs:
                    errors.append(f"{rel}:{lineno}: missing heading #{fragment}")
            continue
        seen += 1
        target, fragment = split_dest(dest)
        if not target:
            if fragment and fragment not in own_slugs:
                errors.append(f"{rel}:{lineno}: missing heading #{fragment}")
            continue
        if target.startswith(_SKIP_SCHEMES):
            workflow = _WORKFLOW_URL.match(target)
            if workflow:
                name = workflow.group("name")
                workflow_path = f".github/workflows/{name}"
                if workflow_path not in tracked:
                    errors.append(
                        f"{rel}:{lineno}: badge or workflow URL names missing {workflow_path}"
                    )
            elif "/actions/workflows/" in target and "kumarlakshya24/personal-projects" in target:
                errors.append(f"{rel}:{lineno}: unrecognized workflow URL {target}")
            continue
        resolved = (path.parent / target).resolve()
        try:
            resolved.relative_to(ROOT)
        except ValueError:
            errors.append(f"{rel}:{lineno}: link escapes the repository: {target}")
            continue
        repo_path = resolved.relative_to(ROOT).as_posix()
        if resolved.is_file():
            if repo_path not in tracked:
                errors.append(f"{rel}:{lineno}: {repo_path} is not a committed file")
        elif resolved.is_dir():
            prefix = repo_path.rstrip("/") + "/"
            if not any(item.startswith(prefix) for item in tracked):
                errors.append(f"{rel}:{lineno}: no committed files under {repo_path}/")
        else:
            errors.append(f"{rel}:{lineno}: missing path {repo_path}")
            continue
        if fragment and repo_path.endswith(".md"):
            if repo_path not in slug_cache:
                slug_cache[repo_path] = headings((ROOT / repo_path).read_text(encoding="utf-8"))
            if fragment not in slug_cache[repo_path]:
                errors.append(f"{rel}:{lineno}: {repo_path} has no heading #{fragment}")
    if seen == 0:
        errors.append(f"{rel}: no links or images found")
    return errors, seen


def main(argv: list[str]) -> int:
    files = argv[1:] or list(DEFAULT_FILES)
    tracked = tracked_paths()
    errors: list[str] = []
    checked = 0
    for rel in files:
        file_errors, seen = check_file(rel, tracked)
        errors.extend(file_errors)
        checked += seen
    print(f"checked {len(files)} markdown file(s), {checked} links and images")
    if errors:
        print(f"{len(errors)} problem(s):")
        for item in errors:
            print(f"  {item}")
        return 1
    print("links, images, and workflow badges ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
