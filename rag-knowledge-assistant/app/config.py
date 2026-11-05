"""Central configuration. Every knob is an environment variable (see .env.example).

No secrets have defaults; provider keys are read from the environment only.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- infrastructure
    # Connection parts; the password has no default and is read only from the environment / .env.
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "rag"
    postgres_db: str = "rag"
    postgres_password: SecretStr | None = None
    # Optional full libpq URL/conninfo; when unset it is assembled from the POSTGRES_* parts above.
    database_url: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    users_file: Path = ROOT / "config" / "users.yaml"
    docs_dir: Path = ROOT / "data" / "sample_docs"
    log_level: str = "INFO"

    # --- embeddings: onnx | hash | openai_compat
    embedding_provider: str = "onnx"
    embedding_model_dir: Path = ROOT / "models" / "all-MiniLM-L6-v2"
    embedding_dim: int = 384
    embedding_batch_size: int = 32
    embedding_api_base: str = "https://api.openai.com/v1"
    embedding_api_model: str = "text-embedding-3-small"
    embedding_api_key: str | None = None

    # --- reranker: onnx | none
    reranker_provider: str = "onnx"
    # int8 dynamic-quantized export (scripts/fetch_models.py builds it from the verified fp32 weights):
    # same end-to-end eval score as fp32, ~40% lower p95 (see eval_results/runs/*-int8-reranker).
    reranker_model_dir: Path = ROOT / "models" / "ms-marco-MiniLM-L-6-v2-int8"
    reranker_max_length: int = 320

    # --- LLM: extractive | anthropic | openai_compat
    llm_provider: str = "extractive"
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "low"
    llm_max_tokens: int = 1024
    llm_timeout_s: float = 20.0
    openai_compat_base_url: str = "http://localhost:11434/v1"
    openai_compat_api_key: str | None = None
    # Prices used for cost estimates (USD per million tokens). Defaults are
    # Anthropic list prices for claude-opus-5-5; override for your model.
    llm_price_input_per_mtok: float = 4.0
    llm_price_output_per_mtok: float = 20.0
    # Model the cost projection assumes when running the offline extractive generator.
    cost_projection_model: str = "claude-opus-5-5"

    # --- chunking
    chunk_max_tokens: int = 200
    chunk_min_tokens: int = 40

    # --- retrieval
    candidate_k: int = 50
    final_k: int = 5
    fusion_method: str = "rrf"  # rrf | weighted
    hybrid_vector_weight: float = 0.5
    hybrid_bm25_weight: float = 0.5
    rrf_k: int = 60
    bm25_k1: float = 1.2
    bm25_b: float = 0.75
    hnsw_ef_search: int = 100
    multiquery_variants: int = 3

    # --- evidence gate (refusal). Cross-encoder logit / cosine thresholds.
    # Chosen by scripts/calibrate.py on the held-out eval/calibration.yaml (not the eval set).
    min_rerank_score: float = -7.0
    min_vector_score: float = 0.35
    min_sentence_score: float = -12.0

    # --- latency budgets (ms)
    retrieval_budget_ms: int = 800
    rerank_budget_ms: int = 2500
    generation_budget_ms: int = 20000

    # --- semantic cache
    cache_enabled: bool = True
    # 0.85: measured sweep in eval_results shows false hits begin at 0.75 (with guard); keep margin
    cache_similarity_threshold: float = 0.85
    cache_ttl_s: int = 6 * 3600

    # --- governance
    pii_mode: str = "external"  # off | external (redact before external LLMs) | always
    injection_mode: str = "strip"  # off | flag | strip | drop
    admin_role: str = "kb_admin"

    default_profile: str = Field(default="full")


    @model_validator(mode="after")
    def _assemble_database_url(self) -> "Settings":
        if not self.database_url:
            from psycopg.conninfo import make_conninfo

            parts = {"host": self.postgres_host, "port": self.postgres_port,
                     "user": self.postgres_user, "dbname": self.postgres_db}
            if self.postgres_password is not None:
                parts["password"] = self.postgres_password.get_secret_value()
            self.database_url = make_conninfo(**parts)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
