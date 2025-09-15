"""
Speech-to-Text Consumer Service

This service consumes audio messages from Kafka, downloads audio files from S3,
processes them using Whisper model for transcription, and stores transcript
segments in the database.

Author: AgentScoring Team
Date: 2025-09-15
"""

import io
import json
import logging
from datetime import datetime
from typing import Optional

import boto3
from confluent_kafka import Consumer
from faster_whisper import WhisperModel
from sqlalchemy.orm import Session

from app.common.config import settings
from app.common.db import get_session
from app.common.models import Call, TranscriptSegment

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stt_consumer")

# Initialize Whisper model for speech-to-text processing
# Using 'base' model for good balance between speed and accuracy
model = WhisperModel("base", device="cpu", compute_type="int8")

# Initialize S3 client for audio file downloads
s3_client = boto3.client(
    "s3",
    endpoint_url=settings.s3_endpoint,
    aws_access_key_id=settings.s3_access_key,
    aws_secret_access_key=settings.s3_secret_key,
    region_name="us-east-1"
)

# Configure Kafka consumer
consumer = Consumer({
    "bootstrap.servers": settings.kafka_bootstrap,
    "group.id": "stt-consumer",
    "auto.offset.reset": "earliest"
})
consumer.subscribe([settings.topic_audio_ready])

logger.info("STT consumer started. Waiting for audio messages...")


def process_audio_message(payload: bytes) -> None:
    """
    Process a single audio message from Kafka queue.
    
    Args:
        payload: JSON-encoded message containing call_id and s3_key
        
    Raises:
        Exception: Various exceptions during audio processing or database operations
    """
    try:
        # Parse message payload
        data = json.loads(payload)
        call_id = data["call_id"]
        s3_key = data["s3_key"]
        
        logger.info(f"Processing audio for call_id: {call_id}")
        
        # Download audio file from S3
        audio_obj = s3_client.get_object(Bucket=settings.s3_bucket, Key=s3_key)
        audio_bytes = audio_obj["Body"].read()
        
        # Process audio with Whisper model
        # VAD filter removes silence for better transcription quality
        segments, info = model.transcribe(
            io.BytesIO(audio_bytes),
            vad_filter=True,
            vad_parameters={"min_speech_duration_ms": 250}
        )
        
        # Store transcript segments in database
        db_session: Session = get_session()
        
        try:
            # Save each transcript segment
            for segment in segments:
                transcript = TranscriptSegment(
                    call_id=call_id,
                    speaker=getattr(segment, "speaker", None),
                    start_time=segment.start,
                    end_time=segment.end,
                    text=segment.text
                )
                db_session.add(transcript)
            
            # Update call status to COMPLETED and record processing timestamp
            call = db_session.query(Call).filter_by(call_id=call_id).first()
            if call:
                call.status = 'COMPLETED'
                call.processed_at = datetime.utcnow()
            
            # Commit all changes
            db_session.commit()
            logger.info(f"Successfully saved transcript for call_id: {call_id}")
            
        finally:
            db_session.close()
            
    except Exception as e:
        logger.error(f"Error processing audio for call_id {call_id}: {e}")
        raise


def main() -> None:
    """
    Main consumer loop.
    
    Continuously polls Kafka for new audio messages and processes them.
    """
    while True:
        # Poll for new messages (1 second timeout)
        message = consumer.poll(1.0)
        
        if message is None:
            continue
            
        if message.error():
            logger.error(f"Kafka error: {message.error()}")
            continue
            
        # Process the audio message
        try:
            process_audio_message(message.value())
        except Exception as e:
            logger.error(f"Failed to process message: {e}")


if __name__ == "__main__":
    main()
