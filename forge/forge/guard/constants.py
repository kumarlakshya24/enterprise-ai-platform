"""Non-overridable denylists.

Policy YAML can shrink the allowlist. It cannot grant a name in these sets.
`pathlib` and `sqlite3` are intentionally absent: they are policy denials, so a
weaker policy file is something the regression gate can catch.
"""

from __future__ import annotations

HARD_DENY_MODULES = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "socket",
        "ctypes",
        "shutil",
        "pickle",
        "marshal",
        "importlib",
        "pty",
        "fcntl",
        "signal",
        "multiprocessing",
        "threading",
        "asyncio",
        "_thread",
        "concurrent",
        "http",
        "urllib",
        "requests",
        "httpx",
        "ftplib",
        "smtplib",
        "poplib",
        "imaplib",
        "nntplib",
        "telnetlib",
        "socketserver",
        "webbrowser",
        "code",
        "codeop",
        "compileall",
        "pdb",
        "runpy",
        "builtins",
        "ssl",
        "select",
        "selectors",
        "mmap",
        "resource",
        "syslog",
        "grp",
        "pwd",
        "spwd",
        "crypt",
        "posix",
        "nt",
        "_posixsubprocess",
        "_socket",
        "_ctypes",
        "xmlrpc",
        "wsgiref",
        "ensurepip",
        "venv",
        "pip",
        "site",
        "sysconfig",
        "faulthandler",
        "gc",
        "inspect",
        "dis",
        "ast",
        "types",
        "opcode",
        "pkgutil",
        "modulefinder",
        "zipimport",
        "zipfile",
        "tarfile",
        "gzip",
        "bz2",
        "lzma",
        "io",
    }
)

DENIED_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "open",
        "__import__",
        "input",
        "breakpoint",
        "help",
        "exit",
        "quit",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "memoryview",
        "object",
        "super",
        "type",
        "classmethod",
        "staticmethod",
        "property",
        "copyright",
        "credits",
        "license",
        "dir",
    }
)

# Frame and generator attributes used to walk out of a restricted namespace.
DENIED_ATTRS = frozenset(
    {
        "gi_frame",
        "gi_code",
        "cr_frame",
        "cr_code",
        "ag_frame",
        "ag_code",
        "f_globals",
        "f_locals",
        "f_builtins",
        "tb_frame",
        "tb_next",
        "f_back",
    }
)

KNOWN_TOOLS = frozenset({"python", "read_file", "write_file", "list_dir", "shell"})
SHELL_TOOL = "shell"
