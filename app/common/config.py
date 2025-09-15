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

    class Config:
        """Pydantic configuration."""
        env_file = ".env"


# Global settings instance
settings = Settings()
