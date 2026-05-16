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

    log_level: str = "INFO"


settings = Settings()
