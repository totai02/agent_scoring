from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    avaya_base_url: str = "http://localhost:8000"
    scoring_service_url: str = "http://localhost:8080/scoring"
    kafka_bootstrap: str = "localhost:9092"
    kafka_group_ingestion: str = "ingestion-group"
    kafka_group_download: str = "download-group"
    kafka_group_scoring: str = "scoring-group"
    topic_calls_raw: str = "calls.raw"
    topic_calls_enriched: str = "calls.enriched"
    topic_audio_ready: str = "audio.ready"
    topic_scoring_results: str = "scoring.results"
    s3_bucket: str = "ccas-audio-dev"
    s3_endpoint: str | None = None  # e.g., for MinIO
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    max_download_concurrency: int = 16
    poll_interval_seconds: int = 30
    poll_window_seconds: int = 60  # length of window
    poll_delay_seconds: int = 90   # how far behind now we poll start
    database_url: str | None = None

    class Config:
        env_file = ".env"

settings = Settings()
