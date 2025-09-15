import asyncio
import httpx
import json
from confluent_kafka import Consumer
from app.common.config import settings
import random
import boto3
from botocore.client import Config
from io import BytesIO
from datetime import datetime
from .kafka_producer import get_producer

DLQ_TOPIC = 'scoring.results.dlq'
MAX_RETRIES = 3

_s3 = None

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

async def call_scoring_service_from_bytes(call_id: str, audio_bytes: bytes):
    bio = BytesIO(audio_bytes)
    bio.name = f"{call_id}.wav"  # help frameworks
    files = {'audio': (bio.name, bio, 'audio/wav')}
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(settings.scoring_service_url, files=files)
        r.raise_for_status()
        return r.json()

async def fetch_audio_s3(key: str) -> bytes:
    s3 = get_s3()
    obj = s3.get_object(Bucket=settings.s3_bucket, Key=key)
    return obj['Body'].read()

async def run_scoring():
    consumer = Consumer({
        'bootstrap.servers': settings.kafka_bootstrap,
        'group.id': settings.kafka_group_scoring,
        'auto.offset.reset': 'earliest'
    })
    consumer.subscribe([settings.topic_audio_ready])
    producer = get_producer()

    while True:
        msg = consumer.poll(0.2)
        if msg is None:
            await asyncio.sleep(0.05)
            continue
        if msg.error():
            print(f"[scoring][err]{msg.error()}")
            continue
        data = json.loads(msg.value())
        call_id = data['call_id']
        s3_key = data['s3_key']
        attempt = 0
        while attempt < MAX_RETRIES:
            try:
                audio_bytes = await fetch_audio_s3(s3_key)
                result = await call_scoring_service_from_bytes(call_id, audio_bytes)
                print(f"[scoring] {call_id} -> {result}")
                break
            except Exception as ex:
                attempt += 1
                if attempt >= MAX_RETRIES:
                    err_payload = {
                        "call_id": call_id,
                        "error": str(ex),
                        "attempts": attempt,
                        "s3_key": s3_key,
                        "ts": datetime.utcnow().isoformat()
                    }
                    producer.produce(DLQ_TOPIC, key=call_id, value=json.dumps(err_payload))
                    producer.flush()
                    print(f"[scoring][dlq] {call_id} {ex}")
                else:
                    backoff = (2 ** (attempt - 1)) + random.uniform(0,0.3)
                    await asyncio.sleep(backoff)

if __name__ == '__main__':
    asyncio.run(run_scoring())
