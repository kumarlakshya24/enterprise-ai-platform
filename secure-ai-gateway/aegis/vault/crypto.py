"""AES-256-GCM envelope with key ids (for rotation) and context-bound associated data."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class VaultIntegrityError(Exception):
    """Ciphertext did not authenticate: wrong key, wrong context (AAD), or tampering."""


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class VaultCipher:
    def __init__(self, keys: dict[str, bytes], active_kid: str) -> None:
        if active_kid not in keys:
            raise ValueError("active key id not in keyring")
        for kid, key in keys.items():
            if len(key) != 32:
                raise ValueError(f"key {kid} must be 32 bytes")
        self._keys = dict(keys)
        self.active_kid = active_kid
        self._index_key = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=b"aegis-vault-index-v1"
        ).derive(keys[active_kid])

    def encrypt(self, plaintext: str, aad: bytes) -> str:
        nonce = os.urandom(12)
        ct = AESGCM(self._keys[self.active_kid]).encrypt(nonce, plaintext.encode(), aad)
        return f"{self.active_kid}.{_b64e(nonce)}.{_b64e(ct)}"

    def decrypt(self, token: str, aad: bytes) -> str:
        try:
            kid, nonce_s, ct_s = token.split(".")
            key = self._keys[kid]
            return AESGCM(key).decrypt(_b64d(nonce_s), _b64d(ct_s), aad).decode()
        except (ValueError, KeyError, InvalidTag) as exc:
            raise VaultIntegrityError("vault ciphertext failed authentication") from exc

    def index(self, *parts: str) -> str:
        """Keyed fingerprint used to look up an existing placeholder. Not reversible without the key."""
        msg = "\x1f".join(parts).encode()
        return hmac.new(self._index_key, msg, hashlib.sha256).hexdigest()[:32]
