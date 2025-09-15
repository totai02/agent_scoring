# STT Pipeline - Scaling & Production Hardening Notes

## Throughput Planning
Estimate calls per day & peak bursts. Size Kafka partitions accordingly (target < 10MB/s per partition for comfort).

## Bottlenecks
1. **Avaya API rate limits** -> use multiple staggered pollers with disjoint windows.
2. **STT processing CPU/GPU** -> autoscale via queue lag or p95 latency. faster-whisper uses GPU when available.
3. **S3 bandwidth** -> parallel multipart upload for large audio files.
4. **Database writes** -> optimize bulk transcript segment inserts.

## Data Quality
- Implement schema validation (Pydantic) at consumer boundary.
- Dead letter sampling & automated reprocessing jobs for failed STT attempts.
- Audio format validation before processing.

## Reliability
- Use exactly-once semantics pattern: produce->DB in single outbox table then Kafka Connect outbox if stronger guarantees needed.
- Graceful shutdown: stop polling, drain tasks, commit offsets, flush producers.
- STT model caching and warm-up strategies.

## Security
- Rotate credentials (IAM roles preferred) - avoid embedding keys.
- Encrypt audio files at rest in S3.
- Sanitize transcript data if required for compliance.

## Cost Optimization
- Compress audio to FLAC after download; keep raw only 30d.
- Use smaller STT models for cost vs. accuracy trade-offs.
- Implement audio preprocessing (VAD) to reduce processing time.

## Monitoring
- Track STT processing latency and accuracy metrics.
- Monitor queue depths and consumer lag.
- Alert on failed transcription rates.

## Chaos Testing
- Inject 500/timeout from Avaya & STT service to validate fallback.
- Test with corrupted/invalid audio files.
- Network partition testing between services.

