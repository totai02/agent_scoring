# Scaling & Production Hardening Notes

## Throughput Planning
Estimate calls per day & peak bursts. Size Kafka partitions accordingly (target < 10MB/s per partition for comfort).

## Bottlenecks
1. Avaya API rate limits -> use multiple staggered pollers with disjoint windows.
2. Scoring service CPU/GPU -> autoscale via queue lag or p95 latency.
3. S3 bandwidth -> parallel multipart upload.

## Data Quality
- Implement schema validation (Pydantic) at consumer boundary.
- Dead letter sampling & automated reprocessing jobs.

## Reliability
- Use exactly-once semantics pattern: produce->DB in single outbox table then Kafka Connect outbox if stronger guarantees needed.
- Graceful shutdown: stop polling, drain tasks, commit offsets, flush producers.

## Security
- Rotate credentials (IAM roles preferred) - avoid embedding keys.

## Cost Optimization
- Compress audio to FLAC after download; keep raw only 30d.

## Chaos Testing
- Inject 500/timeout from Avaya & scoring to validate fallback.

