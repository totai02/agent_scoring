"""
Configuration Management

This module provides application-wide configuration settings using
Pydantic Settings for the AgentScoring STT pipeline system.

Environment variables are loaded from .env file and can be overridden
by system environment variables.

Author: AgentScoring Team
Date: 2025-09-15
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application configuration settings.
    
    All settings can be overridden via environment variables.
    Settings are loaded from .env file by default.
    """
    
    # External service URLs
    avaya_base_url: str = "http://localhost:8000"
    
    # Kafka configuration
    kafka_bootstrap: str = "localhost:9092"
    kafka_group_download: str = "download-group"
    
    # Kafka topics
    topic_calls_raw: str = "calls.raw"
    topic_calls_enriched: str = "calls.enriched"
    topic_audio_ready: str = "audio.ready"
    
    # S3/Object storage configuration
    s3_bucket: str = "ccas-audio-dev"
    s3_endpoint: str | None = None  # Optional endpoint for MinIO/S3-compatible
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    
    # Processing configuration
    max_download_concurrency: int = 16
    poll_interval_seconds: int = 30
    poll_window_seconds: int = 60   # Length of time window for polling
    poll_delay_seconds: int = 90    # Delay behind current time to start polling
    
    # Database configuration
    database_url: str | None = None
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "agent_scoring"
    db_user: str = "agent"
    db_password: str = "agentpw"
    
    # STT Consumer optimization settings
    stt_max_workers: int = 4
    db_pool_size: int = 10
    db_max_overflow: int = 20
    stt_batch_size: int = 10
    poll_timeout: float = 1.0
    
    # Whisper model configuration
    whisper_model_size: str = "base"  # tiny, base, small, medium, large
    whisper_device: str = "cpu"       # cpu or cuda
    whisper_compute_type: str = "int8"  # int8, int16, float16, float32

    # Advanced STT optimization flags
    stt_shared_model: bool = True  # Use single shared Whisper model for all workers
    stt_metrics_port: int = 9300   # Prometheus metrics port (if >0 then enabled)
    stt_max_transcribe_seconds: int | None = None  # Safety timeout per transcription
    stt_log_verbose: bool = False  # Verbose per-segment logging
    stt_backpressure_factor: int = 2  # pending_futures threshold multiplier vs workers
    stt_commit_interval: float = 5.0  # seconds between forced offset commits

    class Config:
        """Pydantic configuration."""
        env_file = ".env"


# Global settings instance
settings = Settings()
