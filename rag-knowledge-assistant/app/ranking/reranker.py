"""Cross-encoder re-ranking.

The cross-encoder (cross-encoder/ms-marco-MiniLM-L-6-v2, ONNX) reads the query and
passage *together* and outputs a relevance logit, which is far more precise than
the bi-encoder cosine used for first-stage recall, but O(candidates) model calls
per query, which is why it only sees the top-N fused candidates.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

from app.config import Settings


class Reranker(Protocol):
    name: str

    def score(self, query: str, passages: Sequence[str]) -> np.ndarray: ...


class OnnxCrossEncoder:
    def __init__(self, model_dir: Path, max_length: int = 320, batch_size: int = 16):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_path = model_dir / "onnx" / "model.onnx"
        if not model_path.exists():
            raise FileNotFoundError(f"reranker model not found in {model_dir}; run scripts/fetch_models.py")
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.input_names = {i.name for i in self.session.get_inputs()}
        self.batch_size = batch_size
        self.name = f"onnx:{model_dir.name}"

    def score(self, query: str, passages: Sequence[str]) -> np.ndarray:
        scores: list[np.ndarray] = []
        for i in range(0, len(passages), self.batch_size):
            batch = list(passages[i:i + self.batch_size])
            enc = self.tokenizer.encode_batch([(query, p) for p in batch])
            feeds = {
                "input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
            }
            if "token_type_ids" in self.input_names:
                feeds["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
            logits = self.session.run(None, feeds)[0]
            scores.append(logits[:, 0])
        return np.concatenate(scores) if scores else np.zeros(0, dtype=np.float32)


def build_reranker(s: Settings) -> Reranker | None:
    p = s.reranker_provider.lower()
    if p == "none":
        return None
    if p == "onnx":
        return OnnxCrossEncoder(s.reranker_model_dir, s.reranker_max_length)
    raise ValueError(f"unknown RERANKER_PROVIDER {s.reranker_provider!r}")
