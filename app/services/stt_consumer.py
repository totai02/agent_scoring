import os
import io
import logging
from sqlalchemy.orm import Session
from app.common.db import get_session
from app.common.models import TranscriptSegment
from app.common.config import settings
import boto3
from faster_whisper import WhisperModel
from confluent_kafka import Consumer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stt_consumer")

# Khởi tạo model Whisper
model = WhisperModel("base", device="cpu", compute_type="int8")

# Kết nối S3
s3 = boto3.client(
    "s3",
    endpoint_url=settings.s3_endpoint,
    aws_access_key_id=settings.s3_access_key,
    aws_secret_access_key=settings.s3_secret_key,
    region_name="us-east-1"
)

# Kafka consumer
consumer = Consumer({
    "bootstrap.servers": settings.kafka_bootstrap,
    "group.id": "stt-consumer",
    "auto.offset.reset": "earliest"
})
consumer.subscribe([settings.topic_audio_ready])

logger.info("STT consumer started. Waiting for audio messages...")

while True:
    msg = consumer.poll(1.0)
    if msg is None:
        continue
    if msg.error():
        logger.error(f"Kafka error: {msg.error()}")
        continue
    try:
        payload = msg.value()
        # Giả sử payload là dict chứa thông tin file audio
        import json
        data = json.loads(payload)
        call_id = data["call_id"]
        s3_key = data["s3_key"]

        # Tải file audio từ S3
        audio_obj = s3.get_object(Bucket=settings.s3_bucket, Key=s3_key)
        audio_bytes = audio_obj["Body"].read()

        # Phiên âm bằng Whisper
        segments, info = model.transcribe(io.BytesIO(audio_bytes), vad_filter=True, vad_parameters={"min_speech_duration_ms": 250})

        # Lưu từng đoạn transcript vào DB
        db: Session = get_session()
        for seg in segments:
            transcript = TranscriptSegment(
                call_id=call_id,
                speaker=seg.speaker if hasattr(seg, "speaker") else None,
                start_time=seg.start,
                end_time=seg.end,
                text=seg.text
            )
            db.add(transcript)
        
        # Update Call status to COMPLETED after transcription
        from app.common.models import Call
        from datetime import datetime
        call = db.query(Call).filter_by(call_id=call_id).first()
        if call:
            call.status = 'COMPLETED'
            call.processed_at = datetime.utcnow()  # Record when STT processing completed
        
        db.commit()
        db.close()
        logger.info(f"Đã lưu transcript cho call_id {call_id}")
    except Exception as e:
        logger.error(f"Lỗi xử lý audio: {e}")
