"""Sandbox child process.

Invoked as `python -I -B forge/sandbox/child.py`. The parent already decided the
call is allowed. This process repeats the AST gate, installs an audit hook,
applies rlimits, and only then executes the snippet.
"""

from __future__ import annotations

import json
import resource
import sys
from pathlib import Path


def _bootstrap() -> None:
    root = Path(__file__).resolve().parents[2]
    entry = str(root)
    if entry not in sys.path:
        sys.path.insert(0, entry)


_bootstrap()

from forge.guard.ast_guard import check_python  # noqa: E402
from forge.guard.imports import GuardError, classify_module  # noqa: E402
from forge.sandbox.hook import install_audit_hook  # noqa: E402

_STDOUT = sys.stdout


def emit(payload: dict[str, object]) -> None:
    _STDOUT.write(json.dumps(payload) + "\n")
    _STDOUT.flush()


class OutputCap:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._parts: list[str] = []
        self.size = 0
        self.hit = False

    def write(self, text: str) -> None:
        if self.hit:
            return
        encoded = text.encode("utf-8")
        if self.size + len(encoded) > self.limit:
            self.hit = True
            remain = self.limit - self.size
            self._parts.append(encoded[:remain].decode("utf-8", errors="ignore"))
            self.size = self.limit
            return
        self._parts.append(text)
        self.size += len(encoded)

    def text(self) -> str:
        return "".join(self._parts)


def _try_limit(resource_id: int, pair: tuple[int, int]) -> None:
    try:
        resource.setrlimit(resource_id, pair)
    except (ValueError, OSError):
        return


def apply_rlimits(req: dict[str, object]) -> None:
    memory_mb = int(req.get("max_memory_mb") or 256)
    memory = memory_mb * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    except (ValueError, OSError) as exc:
        # Fail closed: never execute if the memory ceiling could not be installed.
        raise MemoryError(str(exc)) from exc
    cpu = max(1, int(req.get("cpu_seconds") or 2))
    _try_limit(resource.RLIMIT_CPU, (cpu, cpu))
    _try_limit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    _try_limit(resource.RLIMIT_CORE, (0, 0))
    _try_limit(resource.RLIMIT_NPROC, (0, 0))


def make_builtins(allow: set[str], deny: set[str], cap: OutputCap) -> dict[str, object]:
    real_import = __import__

    def restricted_import(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if level:
            raise ImportError("relative import denied")
        if classify_module(name, allow=allow, deny=deny):
            raise ImportError(f"import denied: {name.split('.', 1)[0]}")
        return real_import(name, globals, locals, fromlist, level)

    def sandbox_print(*args: object, **kwargs: object) -> None:
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        if not isinstance(sep, str):
            sep = " "
        if not isinstance(end, str):
            end = "\n"
        cap.write(sep.join(str(arg) for arg in args) + end)

    return {
        "False": False,
        "None": None,
        "True": True,
        "__import__": restricted_import,
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "bytearray": bytearray,
        "bytes": bytes,
        "chr": chr,
        "dict": dict,
        "divmod": divmod,
        "enumerate": enumerate,
        "filter": filter,
        "float": float,
        "format": format,
        "frozenset": frozenset,
        "hash": hash,
        "hex": hex,
        "int": int,
        "isinstance": isinstance,
        "iter": iter,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "next": next,
        "oct": oct,
        "ord": ord,
        "pow": pow,
        "print": sandbox_print,
        "range": range,
        "repr": repr,
        "reversed": reversed,
        "round": round,
        "set": set,
        "slice": slice,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
    }


def execute(req: dict[str, object]) -> dict[str, object]:
    code = str(req.get("code") or "")
    allow = set(req.get("allow_imports") or [])
    deny = set(req.get("deny_imports") or [])
    max_output = int(req.get("max_output_bytes") or 8192)
    max_code = int(req.get("max_code_bytes") or 4000)
    try:
        check_python(code, allow=allow, deny=deny, max_bytes=max_code)
    except GuardError as exc:
        return {"status": "deny", "rule": exc.rule, "stdout": "", "error": exc.detail}
    cap = OutputCap(max_output)
    namespace: dict[str, object] = {
        "__builtins__": make_builtins(allow, deny, cap),
        "__name__": "__sandbox__",
    }
    try:
        exec(compile(code, "<sandbox>", "exec"), namespace, namespace)
    except MemoryError:
        return {"status": "limited", "rule": "R-LIMIT-MEMORY", "stdout": cap.text(), "error": "MemoryError"}
    except PermissionError as exc:
        text = str(exc)
        rule = "R-SANDBOX-OPEN" if "R-SANDBOX-OPEN" in text else "R-SANDBOX-AUDIT"
        return {"status": "deny", "rule": rule, "stdout": cap.text(), "error": rule}
    except SystemExit:
        return {"status": "deny", "rule": "R-SANDBOX-EXIT", "stdout": cap.text(), "error": "SystemExit"}
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"[:180]
        return {"status": "error", "rule": "R-SANDBOX-EXCEPTION", "stdout": cap.text(), "error": message}
    if cap.hit:
        return {"status": "limited", "rule": "R-LIMIT-OUTPUT", "stdout": cap.text(), "error": "output cap"}
    return {"status": "ok", "rule": "R-ALLOW", "stdout": cap.text(), "error": ""}


def main() -> int:
    try:
        req = json.loads(sys.stdin.read() or "{}")
        apply_rlimits(req)
        install_audit_hook()
        emit(execute(req))
    except MemoryError:
        emit({"status": "limited", "rule": "R-LIMIT-MEMORY", "stdout": "", "error": "MemoryError"})
    except Exception as exc:
        emit(
            {
                "status": "error",
                "rule": "R-SANDBOX-CRASH",
                "stdout": "",
                "error": type(exc).__name__,
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
