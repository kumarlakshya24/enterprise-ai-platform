"""Embedding providers, selected by EMBEDDING_PROVIDER.

* onnx         - sentence-transformers/all-MiniLM-L6-v2 exported to ONNX, run on CPU
                 with onnxruntime (mean pooling + L2 norm, identical to the reference
                 sentence-transformers pipeline). No torch dependency.
* hash         - deterministic hashed bag-of-words; used by tests only.
* openai_compat- any OpenAI-compatible /embeddings endpoint (OpenAI, vLLM, Ollama, TEI).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np

from app.config import Settings


class Embedder(Protocol):
    dim: int
    name: str

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


def _l2(x: np.ndarray) -> np.ndarray:
    return x / np.clip(np.linalg.norm(x, axis=1, keepdims=True), 1e-12, None)


class OnnxEmbedder:
    def __init__(self, model_dir: Path, batch_size: int = 32, max_length: int = 256):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_path = model_dir / "onnx" / "model.onnx"
        if not model_path.exists():
            model_path = model_dir / "model.onnx"
        if not model_path.exists():
            raise FileNotFoundError(f"embedding model not found in {model_dir}; run scripts/fetch_models.py")
        tok_path = next(p for p in [model_dir / "tokenizer.json", model_dir / "onnx" / "tokenizer.json"] if p.exists())
        self.tokenizer = Tokenizer.from_file(str(tok_path))
        self.tokenizer.enable_truncation(max_length)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 0
        self.session = ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])
        self.input_names = {i.name for i in self.session.get_inputs()}
        self.batch_size = batch_size
        self.dim = 384
        self.name = f"onnx:{model_dir.name}"

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        out = []
        for i in range(0, len(texts), self.batch_size):
            enc = self.tokenizer.encode_batch(list(texts[i : i + self.batch_size]))
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feeds = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.input_names:
                feeds["token_type_ids"] = np.zeros_like(ids)
            hidden = self.session.run(None, feeds)[0]  # (b, seq, dim)
            m = mask[..., None].astype(np.float32)
            pooled = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
            out.append(_l2(pooled.astype(np.float32)))
        return np.vstack(out) if out else np.zeros((0, self.dim), dtype=np.float32)


class HashEmbedder:
    """Deterministic, dependency-free embedder for unit/integration tests."""

    def __init__(self, dim: int = 384):
        self.dim = dim
        self.name = "hash"

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        from app.textproc import tokenize

        mat = np.zeros((len(texts), self.dim), dtype=np.float32)
        for r, t in enumerate(texts):
            toks = tokenize(t)
            for tok in toks + [a + "_" + b for a, b in zip(toks, toks[1:], strict=False)]:
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                mat[r, h % self.dim] += 1.0 if (h >> 64) % 2 else -1.0
        return _l2(mat + 1e-6)


class OpenAICompatEmbedder:
    def __init__(self, base_url: str, model: str, api_key: str | None, dim: int):
        import httpx

        self.client = httpx.Client(
            base_url=base_url, timeout=30.0, headers={"Authorization": f"Bearer {api_key}"} if api_key else {}
        )
        self.model, self.dim, self.name = model, dim, f"api:{model}"

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        resp = self.client.post("/embeddings", json={"model": self.model, "input": list(texts), "dimensions": self.dim})
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        return _l2(np.array([d["embedding"] for d in data], dtype=np.float32))


def build_embedder(s: Settings) -> Embedder:
    p = s.embedding_provider.lower()
    if p == "onnx":
        return OnnxEmbedder(s.embedding_model_dir, s.embedding_batch_size)
    if p == "hash":
        return HashEmbedder(s.embedding_dim)
    if p == "openai_compat":
        return OpenAICompatEmbedder(s.embedding_api_base, s.embedding_api_model, s.embedding_api_key, s.embedding_dim)
    raise ValueError(f"unknown EMBEDDING_PROVIDER {s.embedding_provider!r}")


_ws = re.compile(r"\s+")
