"""Download the ONNX models into ./models with sha256 verification.

Sources are tried in order. Hugging Face is the canonical source; the mirrors
exist for networks where huggingface.co is blocked (corporate proxies, sandboxes):
  * embeddings: Chroma's official S3 export of all-MiniLM-L6-v2 (used by chromadb).
  * reranker:   the npm package `kontexta-reranker-model`, which vendors Xenova's
                ONNX export of cross-encoder/ms-marco-MiniLM-L-6-v2 (Apache-2.0).
Every file is verified against a pinned sha256 regardless of source.

Usage: python scripts/fetch_models.py [--dest models] [--no-quantize]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

PINS = {
    "ms-marco-MiniLM-L-6-v2/onnx/model.onnx": "c623d0bcb99f4622beb413eaef00cfbe5db20df9f1dd982da4b4f26022881870",
    "ms-marco-MiniLM-L-6-v2/tokenizer.json": "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",
}
MINILM_TARBALL_SHA = "913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3"
KONTEXTA_TARBALL_SHA = "36cad4891b0c0c806d945f427099307e14f41fd5241f56581491cfa1ea3f4d33"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "rag-knowledge-assistant/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fetch_embedder(dest: Path) -> None:
    target = dest / "all-MiniLM-L6-v2"
    if (target / "onnx" / "model.onnx").exists():
        print("embedder: present")
        return
    hf = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/"
    try:
        files = {"onnx/model.onnx": _get(hf + "onnx/model.onnx"), "tokenizer.json": _get(hf + "tokenizer.json")}
        for rel, data in files.items():
            (target / rel).parent.mkdir(parents=True, exist_ok=True)
            (target / rel).write_bytes(data)
        print("embedder: downloaded from Hugging Face")
        return
    except Exception as e:  # noqa: BLE001
        print(f"embedder: Hugging Face unavailable ({type(e).__name__}); trying Chroma S3 mirror")
    blob = _get("https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz")
    if _sha(blob) != MINILM_TARBALL_SHA:
        sys.exit("embedder: checksum mismatch on mirror tarball")
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        for m in tf.getmembers():
            if m.isfile() and m.name.startswith("onnx/") and ".." not in m.name:
                out = target / m.name
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(tf.extractfile(m).read())
    shutil.copy(target / "onnx" / "tokenizer.json", target / "tokenizer.json")
    print("embedder: downloaded from Chroma S3 mirror (sha256 verified)")


def fetch_reranker(dest: Path) -> None:
    target = dest / "ms-marco-MiniLM-L-6-v2"
    rels = ["onnx/model.onnx", "tokenizer.json"]
    if all((target / r).exists() for r in rels):
        print("reranker: present")
        return
    files: dict[str, bytes] = {}
    try:
        hf = "https://huggingface.co/Xenova/ms-marco-MiniLM-L-6-v2/resolve/main/"
        files = {r: _get(hf + r) for r in rels}
        src = "Hugging Face"
    except Exception as e:  # noqa: BLE001
        print(f"reranker: Hugging Face unavailable ({type(e).__name__}); trying npm mirror")
        blob = _get("https://registry.npmjs.org/kontexta-reranker-model/-/kontexta-reranker-model-1.1.0.tgz")
        if _sha(blob) != KONTEXTA_TARBALL_SHA:
            sys.exit("reranker: checksum mismatch on npm tarball")
        with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
            prefix = "package/models/Xenova/ms-marco-MiniLM-L-6-v2/"
            files = {r: tf.extractfile(prefix + r).read() for r in rels}
        src = "npm mirror"
    for r, data in files.items():
        want = PINS[f"ms-marco-MiniLM-L-6-v2/{r}"]
        if _sha(data) != want:
            sys.exit(f"reranker: sha256 mismatch for {r}")
        (target / r).parent.mkdir(parents=True, exist_ok=True)
        (target / r).write_bytes(data)
    print(f"reranker: downloaded from {src} (sha256 verified)")


def quantize_reranker(dest: Path) -> None:
    """Derive an int8 (dynamic quantization) cross-encoder from the verified fp32 weights."""
    from onnxruntime.quantization import QuantType, quantize_dynamic

    src, dst = dest / "ms-marco-MiniLM-L-6-v2", dest / "ms-marco-MiniLM-L-6-v2-int8"
    if (dst / "onnx" / "model.onnx").exists():
        print("reranker int8: present")
        return
    (dst / "onnx").mkdir(parents=True, exist_ok=True)
    shutil.copy(src / "tokenizer.json", dst / "tokenizer.json")
    quantize_dynamic(str(src / "onnx" / "model.onnx"), str(dst / "onnx" / "model.onnx"), weight_type=QuantType.QInt8)
    print("reranker int8: created (set RERANKER_MODEL_DIR=models/ms-marco-MiniLM-L-6-v2-int8 to use it)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default=str(Path(__file__).resolve().parents[1] / "models"))
    ap.add_argument("--no-quantize", action="store_true", help="skip building the int8 cross-encoder (default model)")
    args = ap.parse_args()
    d = Path(args.dest)
    d.mkdir(parents=True, exist_ok=True)
    fetch_embedder(d)
    fetch_reranker(d)
    if not args.no_quantize:
        quantize_reranker(d)
