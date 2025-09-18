"""
Speech-to-Text Consumer Service

This service consumes audio messages from Kafka, downloads audio files from S3,
processes them using Whisper model for transcription, and stores transcript
segments in the database.

Optimized for high throughput with concurrent processing capabilities.

Author: AgentScoring Team
Date: 2025-09-15
"""

import asyncio
import io
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional, List, Tuple, Dict
from queue import Queue

import boto3
from confluent_kafka import Consumer
from faster_whisper import WhisperModel
from prometheus_client import Counter, Histogram, Gauge, start_http_server
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool
from sqlalchemy import create_engine

from app.common.config import settings
from app.common.db import get_session
from app.common.models import Call, TranscriptSegment

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stt_consumer")

# Configuration constants
MAX_WORKERS = int(getattr(settings, 'stt_max_workers', 4))
DB_POOL_SIZE = int(getattr(settings, 'db_pool_size', 10))
DB_MAX_OVERFLOW = int(getattr(settings, 'db_max_overflow', 20))
BATCH_SIZE = int(getattr(settings, 'stt_batch_size', 10))
POLL_TIMEOUT = float(getattr(settings, 'poll_timeout', 1.0))

###############################################################################
# Model / S3 client management
###############################################################################

# Thread-local storage for models / clients (fallback when not shared)
thread_local = threading.local()

_shared_model: Optional[WhisperModel] = None
_shared_model_lock = threading.Lock()

def _init_model() -> WhisperModel:
    model_size = getattr(settings, 'whisper_model_size', 'base')
    device = getattr(settings, 'whisper_device', 'cpu')
    compute_type = getattr(settings, 'whisper_compute_type', 'int8')
    model = WhisperModel(
        model_size,
        device=device,
        compute_type=compute_type
    )
    logger.info(f"Initialized Whisper model {model_size} on {device} ({compute_type})")
    return model

def get_whisper_model() -> WhisperModel:
    """Return Whisper model (shared or thread-local based on config)."""
    if getattr(settings, 'stt_shared_model', True):
        global _shared_model
        if _shared_model is None:
            with _shared_model_lock:
                if _shared_model is None:
                    _shared_model = _init_model()
        return _shared_model
    # Thread-local fallback
    if not hasattr(thread_local, 'model'):
        thread_local.model = _init_model()
        logger.info(f"Thread {threading.current_thread().name} model ready")
    return thread_local.model

def get_s3_client():
    """Get or create S3 client for current thread."""
    if not hasattr(thread_local, 's3_client'):
        thread_local.s3_client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name="us-east-1"
        )
    return thread_local.s3_client

# Create database engine with connection pooling
db_url = f"postgresql://{settings.db_user}:{settings.db_password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"
engine = create_engine(
    db_url,
    poolclass=QueuePool,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=3600  # Recycle connections every hour
)

###############################################################################
# Prometheus metrics
###############################################################################
METRICS_ENABLED = getattr(settings, 'stt_metrics_port', 0) > 0
PROCESSED_OK = Counter('stt_processed_total', 'Number of successfully processed audio messages')
PROCESSED_FAIL = Counter('stt_failed_total', 'Number of failed audio messages')
TRANSCRIBE_LAT = Histogram('stt_transcribe_seconds', 'Transcription latency seconds')
DOWNLOAD_LAT = Histogram('stt_download_seconds', 'Audio download latency seconds')
END_TO_END_LAT = Histogram('stt_end_to_end_seconds', 'End-to-end processing seconds')
PENDING_GAUGE = Gauge('stt_pending_tasks', 'Number of pending STT tasks')


class STTConsumer:
    """Optimized Speech-to-Text Consumer with concurrent processing & metrics."""
    
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        self.message_queue = Queue(maxsize=BATCH_SIZE * 2)
        self.running = True
        self.stats = {
            'processed': 0,
            'failed': 0,
            'start_time': time.time()
        }
        self._session_factory = None
        self._last_commit_time = time.time()
        
        # Configure Kafka consumer with optimized settings
        self.consumer = Consumer({
            "bootstrap.servers": settings.kafka_bootstrap,
            "group.id": f"stt-consumer-group",  # Unique group for scaling
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,  # Manual commit for better control
            "max.poll.interval.ms": 300000,  # 5 minutes
            "session.timeout.ms": 30000     # 30 seconds
        })
        self.consumer.subscribe([settings.topic_audio_ready])
        
        logger.info(f"STT consumer initialized with {MAX_WORKERS} workers")

        if METRICS_ENABLED:
            port = getattr(settings, 'stt_metrics_port', 9300)
            threading.Thread(target=start_http_server, args=(port,), daemon=True).start()
            logger.info(f"Prometheus metrics server started on :{port}")

    def get_db_session(self) -> Session:
        """Get database session from connection pool (lazy sessionmaker)."""
        if self._session_factory is None:
            from sqlalchemy.orm import sessionmaker
            self._session_factory = sessionmaker(bind=engine)
        return self._session_factory()


    def process_audio_message(self, payload: bytes) -> bool:
        """
        Process a single audio message from Kafka queue.
        
        Args:
            payload: JSON-encoded message containing call_id and s3_key
            
        Returns:
            bool: True if processing succeeded, False otherwise
        """
        call_id = None
        try:
            start_total = time.time()
            verbose = getattr(settings, 'stt_log_verbose', False)
            if verbose:
                logger.info("🔄 Starting audio message processing...")
            
            # Parse message payload
            data = json.loads(payload)
            call_id = data["call_id"]
            s3_key = data["s3_key"]
            if verbose:
                logger.info(f"Processing audio call_id={call_id} key={s3_key}")

            # Early status transition to PROCESSING so monitoring sees active work
            try:
                status_session = self.get_db_session()
                call_obj = status_session.query(Call).filter_by(call_id=call_id).first()
                if call_obj and call_obj.status != 'COMPLETED':
                    call_obj.status = 'PROCESSING'
                    status_session.commit()
                    if verbose:
                        logger.debug(f"call_id={call_id} status -> PROCESSING")
                status_session.close()
            except Exception as _e:
                logger.warning(f"Unable to set PROCESSING status for call_id={call_id}: {_e}")
            
            # Get thread-local clients
            if verbose:
                logger.debug("Acquiring clients")
            s3_client = get_s3_client()
            model = get_whisper_model()
            
            
            # Download audio file from S3
            start_download = time.time()
            try:
                audio_obj = s3_client.get_object(Bucket=settings.s3_bucket, Key=s3_key)
                audio_bytes = audio_obj["Body"].read()
                download_time = time.time() - start_download
                DOWNLOAD_LAT.observe(download_time)
                if verbose:
                    logger.info(f"Downloaded bytes={len(audio_bytes)} t={download_time:.2f}s")
            except Exception as e:
                logger.error(f"❌ S3 download failed: {e}")
                raise
            
            # Process audio with Whisper model
            transcribe_start = time.time()
            try:
                max_secs = getattr(settings, 'stt_max_transcribe_seconds', None)
                # Run transcription (optionally with timeout using a helper thread future inside executor when shared model)
                def _do_transcribe():
                    return model.transcribe(
                        io.BytesIO(audio_bytes),
                        vad_filter=True,
                        vad_parameters={"min_speech_duration_ms": 250}
                    )
                if max_secs and max_secs > 0:
                    # Use a temporary thread if we cannot reuse current due to blocking
                    with ThreadPoolExecutor(max_workers=1) as tmp_exec:
                        future = tmp_exec.submit(_do_transcribe)
                        try:
                            segments, info = future.result(timeout=max_secs)
                        except Exception as ex:
                            future.cancel()
                            logger.error(f"Transcription timeout or error: {ex}")
                            raise
                else:
                    segments, info = _do_transcribe()
                transcribe_time = time.time() - transcribe_start
                TRANSCRIBE_LAT.observe(transcribe_time)
                if verbose:
                    logger.info(f"Transcription done t={transcribe_time:.2f}s")
            except Exception as e:
                logger.error(f"Whisper transcription failed: {e}")
                raise
            
            # Store transcript segments in database
            # Database persistence
            db_session = self.get_db_session()
            
            try:
                # Prepare bulk insert using dictionaries for efficiency
                rows: List[Dict] = []
                seg_count = 0
                for seg in segments:
                    rows.append({
                        'call_id': call_id,
                        'speaker': getattr(seg, 'speaker', None),
                        'start_time': seg.start,
                        'end_time': seg.end,
                        'text': seg.text
                    })
                    seg_count += 1
                if rows:
                    # Use ORM bulk for simplicity (can switch to core insert for even more speed)
                    db_session.bulk_insert_mappings(TranscriptSegment, rows)
                if verbose:
                    logger.info(f"Inserted segments count={seg_count}")
                
                # Update call status to COMPLETED and record processing timestamp
                call = db_session.query(Call).filter_by(call_id=call_id).first()
                if call:
                    call.status = 'COMPLETED'
                    call.processed_at = datetime.utcnow()
                else:
                    logger.warning(f"Call {call_id} not found in database")
                
                # Commit all changes
                db_session.commit()
                total_time = time.time() - start_total
                END_TO_END_LAT.observe(total_time)
                self.stats['processed'] += 1
                PROCESSED_OK.inc()
                logger.info(f"call_id={call_id} ok download={download_time:.2f}s transcribe={transcribe_time:.2f}s total={total_time:.2f}s segs={seg_count}")
                
                return True
                
            except Exception as e:
                logger.error(f"Database operation failed: {e}")
                db_session.rollback()
                raise
            finally:
                db_session.close()
                if verbose:
                    logger.debug("DB session closed")
                
        except Exception as e:
            logger.error(f"call_id={call_id} failed error={e}")
            self.stats['failed'] += 1
            PROCESSED_FAIL.inc()
            return False

    def print_stats(self):
        """Print current processing statistics."""
        runtime = time.time() - self.stats['start_time']
        total_processed = self.stats['processed'] + self.stats['failed']
        
        if runtime > 0:
            rate = total_processed / runtime
            logger.info(f"Stats - Processed: {self.stats['processed']}, "
                       f"Failed: {self.stats['failed']}, "
                       f"Rate: {rate:.2f} msg/sec, "
                       f"Runtime: {runtime:.1f}s")

    def run(self):
        """
        Main consumer loop with concurrent processing.
        """
        logger.info("STT consumer started. Waiting for audio messages...")
        logger.info(f"Subscribed to topic: {settings.topic_audio_ready}")
        logger.info(f"Kafka bootstrap: {settings.kafka_bootstrap}")
        
        last_stats_time = time.time()
        pending_futures = set()
        messages_to_commit = []
        backpressure_factor = getattr(settings, 'stt_backpressure_factor', 2)
        commit_interval = getattr(settings, 'stt_commit_interval', 5.0)
        
        try:
            while self.running:
                # Poll for new messages
                # Apply backpressure: if too many pending, short sleep and process completions
                if len(pending_futures) >= MAX_WORKERS * backpressure_factor:
                    self._process_completed_tasks(pending_futures, messages_to_commit)
                    time.sleep(0.05)
                    continue

                message = self.consumer.poll(POLL_TIMEOUT)
                
                if message is None:
                    # Check for completed tasks and commit offsets
                    self._process_completed_tasks(pending_futures, messages_to_commit)
                    
                    # Print stats every 30 seconds
                    if time.time() - last_stats_time > 30:
                        self.print_stats()
                        logger.info(f"Currently pending tasks: {len(pending_futures)}")
                        logger.info(f"Messages waiting to commit: {len(messages_to_commit)}")
                        last_stats_time = time.time()
                    continue
                    
                if message.error():
                    logger.error(f"Kafka error: {message.error()}")
                    continue
                
                # Log received message details
                logger.debug(f"recv topic={message.topic()} part={message.partition()} offset={message.offset()}")
                
                try:
                    # Try to parse message payload for debugging
                    payload_data = json.loads(message.value().decode('utf-8'))
                    logger.debug(f"payload={payload_data}")
                except Exception as e:
                    logger.error(f"❌ Failed to parse message payload: {e}")
                    logger.error(f"Raw payload: {message.value()}")
                    continue
                
                # Submit message for processing
                future = self.executor.submit(self.process_audio_message, message.value())
                pending_futures.add((future, message))
                PENDING_GAUGE.set(len(pending_futures))
                
                # Process completed tasks if we have too many pending
                if len(pending_futures) >= MAX_WORKERS:
                    self._process_completed_tasks(pending_futures, messages_to_commit)
                
                # Commit offsets periodically by size or time
                now = time.time()
                if messages_to_commit and (len(messages_to_commit) >= BATCH_SIZE or (now - self._last_commit_time) > commit_interval):
                    self._commit_offsets(messages_to_commit)
                    self._last_commit_time = now
                    
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        finally:
            self.shutdown(pending_futures, messages_to_commit)

    def _process_completed_tasks(self, pending_futures, messages_to_commit):
        """Process completed tasks and prepare for committing offsets."""
        completed_futures = []
        successful_tasks = 0
        failed_tasks = 0
        logger.debug(f"Checking {len(pending_futures)} pending tasks")
        
        for future, message in pending_futures:
            if future.done():
                try:
                    success = future.result()
                    if success:
                        messages_to_commit.append(message)
                        successful_tasks += 1
                        logger.debug(f"done offset={message.offset()}")
                    else:
                        failed_tasks += 1
                        logger.warning(f"task failed offset={message.offset()}")
                    completed_futures.append((future, message))
                except Exception as e:
                    logger.error(f"task exception offset={message.offset()} err={e}")
                    failed_tasks += 1
                    completed_futures.append((future, message))
        
        # Remove completed futures
        for completed in completed_futures:
            pending_futures.discard(completed)
            
        if successful_tasks > 0 or failed_tasks > 0:
            logger.info(f"completed tasks={len(completed_futures)} ok={successful_tasks} fail={failed_tasks}")

    def _commit_offsets(self, messages_to_commit):
        """Commit Kafka offsets for successfully processed messages."""
        if messages_to_commit:
            try:
                # Commit the last message offset for each partition
                offsets_to_commit = {}
                for message in messages_to_commit:
                    key = (message.topic(), message.partition())
                    offsets_to_commit[key] = message
                
                # Commit offsets
                # Build list of TopicPartition objects to commit only highest offsets
                for msg in offsets_to_commit.values():
                    self.consumer.commit(msg)
                logger.debug(f"committed messages={len(messages_to_commit)}")
                messages_to_commit.clear()
                
            except Exception as e:
                logger.error(f"Failed to commit offsets: {e}")

    def shutdown(self, pending_futures, messages_to_commit):
        """Graceful shutdown with cleanup."""
        logger.info("Shutting down STT consumer...")
        self.running = False
        
        # Wait for pending tasks to complete
        if pending_futures:
            logger.info(f"Waiting for {len(pending_futures)} pending tasks...")
            for future, message in pending_futures:
                try:
                    future.result(timeout=30)  # Wait up to 30 seconds per task
                    messages_to_commit.append(message)
                except Exception as e:
                    logger.error(f"Task failed during shutdown: {e}")
        
        # Commit remaining offsets
        self._commit_offsets(messages_to_commit)
        
        # Close resources
        self.executor.shutdown(wait=True)
        self.consumer.close()
        
        self.print_stats()
        logger.info("STT consumer shutdown complete")


def main() -> None:
    """
    Main entry point for the STT consumer.
    """
    consumer = STTConsumer()
    consumer.run()


if __name__ == "__main__":
    main()
