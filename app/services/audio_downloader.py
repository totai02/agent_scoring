"""
Audio Downloader Service

This service consumes enriched call messages from Kafka, downloads audio files
from Avaya API, uploads them to S3 storage, and publishes ready messages for
further processing.

Features:
- Concurrent downloads with semaphore control
- Retry logic with exponential backoff
- Dead Letter Queue (DLQ) for failed downloads
- Prometheus metrics for monitoring
- S3 upload with SHA256 verification

Author: AgentScoring Team
Date: 2025-09-15
"""

import asyncio
import hashlib
import json
import random
import time
from datetime import datetime
from typing import Optional

import boto3
import httpx
from botocore.client import Config
from confluent_kafka import Consumer
from prometheus_client import Counter, Histogram, start_http_server

from app.common.config import settings
from app.common.db import get_session
from app.common.models import AudioAsset, Call
from .kafka_producer import get_producer

# Prometheus metrics for monitoring
DOWNLOAD_SUCCESS = Counter(
    'download_success_total', 
    'Successful audio downloads'
)
DOWNLOAD_FAILURE = Counter(
    'download_failure_total', 
    'Failed audio downloads'
)
DOWNLOAD_LATENCY = Histogram(
    'download_latency_seconds', 
    'Latency of Avaya replay download'
)

# Configuration constants
DLQ_TOPIC = 'audio.ready.dlq'
MAX_RETRIES = 5

# Global S3 client (initialized lazily)
_s3_client: Optional[boto3.client] = None


def get_s3_client() -> boto3.client:
    """
    Get or create S3 client instance.
    
    Returns:
        boto3.client: Configured S3 client
    """
    global _s3_client
    if _s3_client is None:
        session = boto3.session.Session()
        _s3_client = session.client(
            's3',
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(signature_version='s3v4'),
            region_name='us-east-1'
        )
    return _s3_client


async def upload_to_s3(call_id: str, audio_data: bytes) -> str:
    """
    Upload audio data to S3 storage.
    
    Args:
        call_id: Unique identifier for the call
        audio_data: Raw audio bytes to upload
        
    Returns:
        str: S3 key path for the uploaded file
    """
    s3_client = get_s3_client()
    date = datetime.utcnow()
    key = f"raw/{date:%Y/%m/%d}/{call_id}.wav"
    
    s3_client.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=audio_data,
        ContentType='audio/wav'
    )
    
    return key


async def download_audio(call_id: str) -> bytes:
    """
    Download audio file from Avaya API.
    
    Args:
        call_id: Unique identifier for the call
        
    Returns:
        bytes: Raw audio data
        
    Raises:
        httpx.HTTPError: If download fails
    """
    url = f"{settings.avaya_base_url}/searchapi"
    params = {"command": "replay", "id": call_id}
    start_time = time.perf_counter()
    
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.content
    finally:
        # Record download latency regardless of success/failure
        DOWNLOAD_LATENCY.observe(time.perf_counter() - start_time)


async def worker_task(
    semaphore: asyncio.Semaphore, 
    call_id: str, 
    producer
) -> None:
    """
    Worker task to download and process a single audio file.
    
    This function:
    1. Downloads audio from Avaya API
    2. Uploads to S3 storage  
    3. Updates database status
    4. Publishes message to Kafka
    5. Handles retries with exponential backoff
    
    Args:
        semaphore: Concurrency control semaphore
        call_id: Unique identifier for the call
        producer: Kafka producer instance
    """
    async with semaphore:
        attempt = 0
        
        while attempt < MAX_RETRIES:
            try:
                # Download audio from Avaya API
                audio_data = await download_audio(call_id)
                
                # Calculate SHA256 hash for integrity verification
                sha256_hash = hashlib.sha256(audio_data).hexdigest()
                
                # Upload to S3 storage
                s3_key = await upload_to_s3(call_id, audio_data)
                
                # Update database with audio asset information
                with get_session() as db_session:
                    # Update call status
                    call = db_session.query(Call).filter_by(call_id=call_id).first()
                    if call:
                        call.status = 'AUDIO_READY'
                    
                    # Create audio asset record
                    audio_asset = AudioAsset(
                        call_id=call_id,
                        s3_key=s3_key,
                        sha256=sha256_hash,
                        size_bytes=len(audio_data),
                        status='READY'
                    )
                    db_session.add(audio_asset)
                    db_session.commit()
                
                # Publish success message to Kafka
                payload = {
                    "call_id": call_id,
                    "s3_key": s3_key,
                    "sha256": sha256_hash
                }
                producer.produce(
                    settings.topic_audio_ready,
                    key=call_id,
                    value=json.dumps(payload)
                )
                
                # Record success metric
                DOWNLOAD_SUCCESS.inc()
                return
                
            except Exception as ex:
                attempt += 1
                
                if attempt >= MAX_RETRIES:
                    # Max retries exceeded - send to DLQ
                    DOWNLOAD_FAILURE.inc()
                    error_payload = {
                        "call_id": call_id,
                        "error": str(ex),
                        "attempts": attempt
                    }
                    producer.produce(
                        DLQ_TOPIC,
                        key=call_id,
                        value=json.dumps(error_payload)
                    )
                    print(f"[downloader][dlq] {call_id} {ex}")
                else:
                    # Wait with exponential backoff before retry
                    backoff_time = (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    await asyncio.sleep(backoff_time)


async def run_downloader() -> None:
    """
    Main downloader service function.
    
    Sets up Kafka consumer, Prometheus metrics server, and processes
    enriched call messages by downloading audio files concurrently.
    """
    # Start Prometheus metrics server
    start_http_server(9200)
    
    # Configure Kafka consumer
    consumer = Consumer({
        'bootstrap.servers': settings.kafka_bootstrap,
        'group.id': settings.kafka_group_download,
        'auto.offset.reset': 'earliest'
    })
    consumer.subscribe([settings.topic_calls_enriched])
    
    # Initialize Kafka producer and concurrency control
    producer = get_producer()
    semaphore = asyncio.Semaphore(settings.max_download_concurrency)
    
    # Get event loop for task scheduling
    loop = asyncio.get_event_loop()
    
    print(f"Audio downloader started. Max concurrency: {settings.max_download_concurrency}")
    
    while True:
        # Poll for new messages
        message = consumer.poll(0.1)
        
        if message is None:
            await asyncio.sleep(0.05)
            continue
            
        if message.error():
            print(f"[consumer][error] {message.error()}")
            continue
            
        # Extract call_id from message key and schedule download task
        call_id = message.key().decode()
        loop.create_task(worker_task(semaphore, call_id, producer))


if __name__ == "__main__":
    asyncio.run(run_downloader())
