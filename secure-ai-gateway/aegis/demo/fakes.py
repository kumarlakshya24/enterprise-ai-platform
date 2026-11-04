"""Synthetic secret-shaped strings, built at runtime so no secret-like literal sits in the repo.

These are not credentials for anything. They only have the *shape* of a key so detectors fire.
"""

from __future__ import annotations

_ALNUM = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"


def fake_openai_key() -> str:
    return "sk-" + "proj-" + _ALNUM[:32]


def fake_aws_key_id() -> str:
    # AWS's own documentation example id.
    return "AKIA" + "IOSFODNN7" + "EXAMPLE"


def fake_github_token() -> str:
    return "ghp" + "_" + (_ALNUM + _ALNUM)[:36]


def fake_jwt() -> str:
    return "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJ" + "zdWIiOiJkZW1vIn0" + "." + "c2lnbmF0dXJlZmFrZTEyMw"


def fake_private_key() -> str:
    begin = "-----BEGIN " + "PRIVATE KEY-----"
    end = "-----END " + "PRIVATE KEY-----"
    return f"{begin}\nMIIEvFAKEKEYDATAFORTESTSONLYnotarealkey0000000000\n{end}"


def fake_high_entropy() -> str:
    return "Zx9" + "Qw7Er5Ty3Ui1Op8As6Df4Gh2Jk0Lz9Xc7Vb"


def fake_password() -> str:
    return "Wint" + "er2026" + "!x"


def fake_db_password() -> str:
    return "Pr0d" + "Passw0rd" + "!"


TEMPLATE_VALUES = {
    "FAKE_PASSWORD": fake_password,
    "FAKE_DB_PASSWORD": fake_db_password,
    "FAKE_OPENAI_KEY": fake_openai_key,
    "FAKE_AWS_KEY_ID": fake_aws_key_id,
    "FAKE_GITHUB_TOKEN": fake_github_token,
    "FAKE_JWT": fake_jwt,
    "FAKE_PRIVATE_KEY": fake_private_key,
    "FAKE_HIGH_ENTROPY": fake_high_entropy,
}


def expand(text: str) -> str:
    """Replace {{FAKE_*}} markers in eval fixtures with runtime-built values."""
    for name, fn in TEMPLATE_VALUES.items():
        text = text.replace("{{" + name + "}}", fn())
    return text
