import asyncio
import httpx
from confluent_kafka import Consumer
from app.common.config import settings
from .kafka_producer import get_producer
import hashlib
import boto3
from botocore.client import Config
from datetime import datetime
from prometheus_client import Counter, Histogram, start_http_server
import time
import random

# Metrics
DOWNLOAD_SUCCESS = Counter('download_success_total', 'Successful audio downloads')
DOWNLOAD_FAILURE = Counter('download_failure_total', 'Failed audio downloads')
DOWNLOAD_LATENCY = Histogram('download_latency_seconds', 'Latency of Avaya replay download')

# Initialize S3 client lazily
_s3 = None
DLQ_TOPIC = 'audio.ready.dlq'
MAX_RETRIES = 5

def get_s3():
    global _s3
    if _s3 is None:
        session = boto3.session.Session()
        _s3 = session.client(
            's3',
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(signature_version='s3v4'),
            region_name='us-east-1'
        )
    return _s3

async def upload_to_s3(call_id: str, data: bytes) -> str:
    s3 = get_s3()
    date = datetime.utcnow()
    key = f"raw/{date:%Y/%m/%d}/{call_id}.wav"
    s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType='audio/wav')
    return key

async def download_audio(call_id: str) -> bytes:
    url = f"{settings.avaya_base_url}/searchapi"
    params = {"command": "replay", "id": call_id}
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.content
    finally:
        DOWNLOAD_LATENCY.observe(time.perf_counter() - start)

async def worker_task(semaphore: asyncio.Semaphore, call_id: str, producer):
    async with semaphore:
        attempt = 0
        while attempt < MAX_RETRIES:
            try:
                audio = await download_audio(call_id)
                sha = hashlib.sha256(audio).hexdigest()
                key = await upload_to_s3(call_id, audio)
                
                # Update database status to AUDIO_READY
                from app.common.db import get_session
                from app.common.models import Call, AudioAsset
                with get_session() as sess:
                    call = sess.query(Call).filter_by(call_id=call_id).first()
                    if call:
                        call.status = 'AUDIO_READY'
                        # Create AudioAsset record
                        audio_asset = AudioAsset(
                            call_id=call_id,
                            s3_key=key,
                            sha256=sha,
                            size_bytes=len(audio),
                            status='READY'
                        )
                        sess.add(audio_asset)
                        sess.commit()
                
                payload = {"call_id": call_id, "s3_key": key, "sha256": sha}
                import json
                producer.produce(settings.topic_audio_ready, key=call_id, value=json.dumps(payload))
                DOWNLOAD_SUCCESS.inc()
                return
            except Exception as ex:
                attempt += 1
                if attempt >= MAX_RETRIES:
                    DOWNLOAD_FAILURE.inc()
                    import json
                    err_payload = {"call_id": call_id, "error": str(ex), "attempts": attempt}
                    producer.produce(DLQ_TOPIC, key=call_id, value=json.dumps(err_payload))
                    print(f"[downloader][dlq] {call_id} {ex}")
                else:
                    backoff = (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    await asyncio.sleep(backoff)

async def run_downloader():
    start_http_server(9200)
    consumer = Consumer({
        'bootstrap.servers': settings.kafka_bootstrap,
        'group.id': settings.kafka_group_download,
        'auto.offset.reset': 'earliest'
    })
    consumer.subscribe([settings.topic_calls_enriched])
    producer = get_producer()
    semaphore = asyncio.Semaphore(settings.max_download_concurrency)

    loop = asyncio.get_event_loop()

    while True:
        msg = consumer.poll(0.1)
        if msg is None:
            await asyncio.sleep(0.05)
            continue
        if msg.error():
            print(f"[consumer][err]{msg.error()}")
            continue
        call_id = msg.key().decode()
        loop.create_task(worker_task(semaphore, call_id, producer))

if __name__ == "__main__":
    asyncio.run(run_downloader())
