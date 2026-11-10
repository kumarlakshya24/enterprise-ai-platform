"""Versioned embedders.

The fake embedder is a hashed bag of tokens. The salt is the model version, so
`emb-v1` and `emb-v2` do not share a vector space even though the dimension
matches. That is the bug a dimension check would miss, and the reason a
generation is bound to one version.

The OpenAI adapter is optional and is not used by `make test`, `make eval`,
or `make up`. It refuses to run without a key, and the key is never logged.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.request
from typing import Protocol

from conduit.errors import EmbedderError
from conduit.models import ModelSpec

FAKE_MODELS: dict[str, ModelSpec] = {
    "emb-v1": ModelSpec("fake-hash", "emb-v1", 256, "conduit-emb-v1"),
    "emb-v2": ModelSpec("fake-hash", "emb-v2", 256, "conduit-emb-v2"),
}

# Placeholders such as [person:subj-ava-chen] and [email] stay one token.
# Splitting them on the hyphen would make every person share "person" and "subj".
_TOKEN = re.compile(r"\[[a-z0-9:_-]+\]|[a-z0-9]+")


def cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))


def _normalize(values: list[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0.0:
        values[0] = 1.0
        norm = 1.0
    return tuple(value / norm for value in values)


class Embedder(Protocol):
    def spec(self, model_version: str) -> ModelSpec: ...

    def embed(self, text: str, model_version: str) -> tuple[float, ...]: ...


class FakeEmbedder:
    def spec(self, model_version: str) -> ModelSpec:
        try:
            return FAKE_MODELS[model_version]
        except KeyError as exc:
            known = ", ".join(sorted(FAKE_MODELS))
            raise EmbedderError(f"unknown model version {model_version!r}; known: {known}") from exc

    def embed(self, text: str, model_version: str) -> tuple[float, ...]:
        spec = self.spec(model_version)
        vector = [0.0] * spec.dim
        for token in _TOKEN.findall(text.lower()):
            # Two hashes. One shared bucket is not enough to impersonate a token,
            # which is what a single-bucket hash does when a repeated word collides.
            for replica in (0, 1):
                digest = hashlib.sha256(f"{spec.salt}|{replica}|{token}".encode()).digest()
                bucket = int.from_bytes(digest[:4], "little") % spec.dim
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vector[bucket] += sign
        return _normalize(vector)


def _post_json(
    url: str, payload: dict[str, object], headers: dict[str, str], timeout: float
) -> dict[str, object]:
    raw = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=raw, headers=headers, method="POST")  # noqa: S310
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict):
        raise EmbedderError("embed provider returned an unexpected body")
    return body


class OpenAIEmbedder:
    """Provider adapter. Tests inject `post` and never open a socket."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        dim: int | None = None,
        post: object | None = None,
        endpoint: str = "https://api.openai.com/v1/embeddings",
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("CONDUIT_OPENAI_API_KEY", "")
        self._model = model or os.environ.get("CONDUIT_OPENAI_MODEL", "text-embedding-3-small")
        self._dim = dim if dim is not None else int(os.environ.get("CONDUIT_OPENAI_DIM", "1536"))
        self._post = post if post is not None else _post_json
        self._endpoint = endpoint

    def spec(self, model_version: str) -> ModelSpec:
        # The generation's version is the provider model name when this adapter is selected.
        version = model_version or self._model
        return ModelSpec("openai", version, self._dim, salt="")

    def embed(self, text: str, model_version: str) -> tuple[float, ...]:
        if not self._api_key:
            raise EmbedderError("CONDUIT_EMBEDDER=openai requires CONDUIT_OPENAI_API_KEY")
        spec = self.spec(model_version)
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self._api_key}",
        }
        payload: dict[str, object] = {"input": text, "model": spec.version}
        try:
            body = self._post(self._endpoint, payload, headers, 10.0)  # type: ignore[operator]
        except EmbedderError:
            raise
        except Exception as exc:
            raise EmbedderError(f"embed provider failed: {exc}") from exc
        data = body.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise EmbedderError("embed provider returned no vector")
        raw_vector = data[0].get("embedding")
        if not isinstance(raw_vector, list) or not raw_vector:
            raise EmbedderError("embed provider returned no vector")
        return tuple(float(value) for value in raw_vector)


def build_embedder(name: str | None = None) -> Embedder:
    selected = name if name is not None else os.environ.get("CONDUIT_EMBEDDER", "fake")
    if selected == "fake":
        return FakeEmbedder()
    if selected == "openai":
        return OpenAIEmbedder()
    raise EmbedderError(f"unknown embedder {selected!r}")
