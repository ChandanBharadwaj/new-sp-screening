from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://screening:screening@localhost:5432/screening"
    database_url_sync: str = "postgresql://screening:screening@localhost:5432/screening"
    redis_url: str = "redis://localhost:6379/0"

    engine_version: str = "0.1.0"

    embedder_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    ner_model: str = "urchade/gliner_small-v2.1"
    ltr_model_path: str = "./artifacts/ltr.txt"

    rerank_top_k: int = 20
    retrieval_top_k: int = 50
    sanctions_rerank_top_k: int = 10

    # Hybrid retrieval blending. "rrf" is score-scale-invariant Reciprocal Rank
    # Fusion (https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf); "max"
    # is the legacy per-field max() blender — kept as a no-restart rollback.
    fusion_mode: str = "rrf"
    rrf_k: int = 60

    # pgvector HNSW recall knob. Default index is built with the pgvector
    # defaults (m=16, ef_construction=64); ef_search at query time is the
    # leverage point that doesn't require an index rebuild.
    hnsw_ef_search: int = 80

    # BGE-small was trained with an asymmetric query-side instruction; without
    # it recall is measurably lower. Documents stay unprefixed (ingesters call
    # `encode_batch`/`encode_one`). Disable for A/B comparison.
    embedder_use_query_prefix: bool = True

    log_level: str = "INFO"


settings = Settings()
