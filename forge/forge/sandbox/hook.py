"""Audit hook installed inside the sandbox process before user code runs.

Importing an allowed stdlib module opens files under the interpreter prefix.
Those reads stay permitted. Writes, host paths, and process/network events do not.
"""

from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path

# Whole prefixes the import machinery does not need. `os` and `marshal` are
# special: CPython lists directories and loads bytecode through them, so only
# the mutating and process events are blocked.
_BLOCKED_PREFIXES = (
    "subprocess.",
    "socket.",
    "ctypes.",
    "shutil.",
    "webbrowser.",
    "pickle.",
    "pty.",
    "multiprocessing.",
    "fcntl.",
    "syslog.",
    "ssl.",
)

_BLOCKED_EVENTS = frozenset(
    {
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
        "os.fork",
        "os.kill",
        "os.remove",
        "os.unlink",
        "os.rmdir",
        "os.rename",
        "os.replace",
        "os.truncate",
        "os.chmod",
        "os.chown",
        "os.link",
        "os.symlink",
        "os.mkdir",
        "os.makedirs",
        "os.open",
        "os.putenv",
        "os.unsetenv",
        "os.chdir",
        "os.startfile",
        "marshal.dumps",
        "marshal.dump",
    }
)

_roots: tuple[Path, ...] = ()
_in_hook = False


def _stdlib_roots() -> tuple[Path, ...]:
    found: list[Path] = []
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        value = sysconfig.get_path(key)
        if value:
            found.append(Path(value).resolve())
    found.append(Path(sys.base_prefix).resolve())
    found.append(Path(sys.prefix).resolve())
    unique: list[Path] = []
    for path in found:
        if path not in unique:
            unique.append(path)
    return tuple(unique)


def _under_stdlib(path: Path) -> bool:
    return any(path == root or root in path.parents for root in _roots)


def _is_write(args: tuple[object, ...]) -> bool:
    mode = args[1] if len(args) > 1 else "r"
    if isinstance(mode, str) and any(ch in mode for ch in "wxa+"):
        return True
    flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
    write_bits = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT
    return bool(flags & write_bits)


def _hook(event: str, args: tuple[object, ...]) -> None:
    global _in_hook
    if _in_hook:
        return
    _in_hook = True
    try:
        if event == "open":
            target = args[0] if args else None
            if isinstance(target, int):
                return
            if not isinstance(target, str | bytes | os.PathLike):
                raise PermissionError("R-SANDBOX-OPEN")
            if _is_write(args):
                raise PermissionError("R-SANDBOX-OPEN")
            try:
                resolved = Path(os.fspath(target)).resolve()
            except OSError as exc:
                raise PermissionError("R-SANDBOX-OPEN") from exc
            if not _under_stdlib(resolved):
                raise PermissionError("R-SANDBOX-OPEN")
            return
        if event in _BLOCKED_EVENTS or event.startswith(_BLOCKED_PREFIXES):
            raise PermissionError("R-SANDBOX-AUDIT")
    finally:
        _in_hook = False


def install_audit_hook() -> None:
    global _roots
    if _roots:
        return
    _roots = _stdlib_roots()
    sys.addaudithook(_hook)
