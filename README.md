# Call Center Agent Scoring Platform

Hệ thống chấm điểm tổng đài viên tự động dựa trên audio cuộc gọi, xây dựng với các thành phần: Avaya API (nguồn), Kafka (event backbone), S3 (lưu trữ audio chuẩn hoá), Database (metadata & kết quả), Scoring Service (ML/NLP), Orchestrator & Workers (đa luồng / ngang hàng), Monitoring.

## 1. Mục tiêu
- Gần real-time ingest audio sau khi cuộc gọi kết thúc (SLA < 2 phút / call)
- Tối ưu độ trễ chấm điểm (song song hoá download + scoring)
- Khả năng mở rộng tuyến tính theo số partition Kafka / số worker
- Đảm bảo idempotency, backpressure, quan sát được (observability)

## 2. Kiến trúc tổng quan
```
        +-------------+        +----------------+        +-----------------+
        |   Avaya     |  HTTP  | Ingestion Poll |  ->    |  Kafka Topic    | (calls.raw)
        |  Search API |<-------|  Scheduler     |  ack   |  calls.raw      |
        +-------------+        +----------------+        +-----------------+
                                                       partition key = call_id
                                                               |
                                    +--------------------------+---------------------------+
                                    |                          |                           |
                             (A) Metadata Enricher      (B) Audio Downloader         (C) Scoring Worker
                                    |                          |                           |
                                    v                          v                           v
                              Kafka calls.enriched     S3 put object (audio)        Kafka scoring.results
                                    |                          |                           |
                                    +-----------+--------------+                           |
                                                |                                          |
                                                v                                          v
                                         Postgres / MySQL <------------------------- Result Consumer
                                          (calls, audio_asset, scoring_result, checkpoints)
```

## 3. Các service chính
1. Ingestion Scheduler / Poller
   - N nhiệm vụ định kỳ (ví dụ mỗi 30s) gọi Avaya Search API theo sliding window (ví dụ T-90s đến T-30s) để tránh cuộc gọi đang diễn ra.
   - Parse XML -> records.
   - Deduplicate dựa trên inums (call_id) bằng Redis set hoặc DB unique index.
   - Publish Kafka `calls.raw` (key=call_id, value metadata JSON).
   - Lưu checkpoint (last polled timestamp) -> bảng `ingestion_checkpoint`.

2. Metadata Enricher (tùy chọn)
   - Chuẩn hoá trường thời gian, tách agent id, khách hàng, skill.
   - Ghi vào PostgreSQL bảng `call` ở trạng thái `PENDING_DOWNLOAD`.
   - Emit event `calls.enriched`.

3. Audio Downloader Worker (đa luồng / async)
   - Consume `calls.enriched` (hoặc trực tiếp `calls.raw` nếu bỏ qua enrich step).
   - Với mỗi call_id: gọi Avaya Replay API lấy binary.
   - Streaming upload trực tiếp lên S3 (avoid disk) -> key: `raw/yyyymmdd/call_id.wav`.
   - Ghi bảng `audio_asset` trạng thái `READY` (checksum SHA256, duration nếu có ffprobe).
   - Publish `audio.ready` event.

4. Scoring Worker
   - Consume `audio.ready`.
   - Download (stream) audio từ S3; gửi multipart tới Scoring API (có thể nội bộ HTTP gRPC).
   - Nhận điểm + breakdown -> ghi bảng `scoring_result`.
   - Cập nhật bảng `call` trạng thái `COMPLETED` + latency metrics.
   - Publish `scoring.results` (phục vụ dashboard / downstream BI).

5. Result Consumer / Exporter
   - Đẩy kết quả real-time sang Elastic / ClickHouse phục vụ phân tích nhanh.

6. Monitoring & Ops
   - Prometheus metrics: ingest_lag_seconds, download_latency_ms, scoring_latency_ms, queue_depth.
   - Alert khi lag > threshold.

## 4. Kafka Topics & Schema (sẽ chi tiết ở file khác)
- calls.raw
- calls.enriched
- audio.ready
- scoring.results

### 4.1 Định nghĩa chi tiết
| Topic | Suggested Partitions | Key | Value Schema (JSON) | Retention | Notes |
|-------|----------------------|-----|---------------------|-----------|-------|
| calls.raw | 12 (scale) | call_id | {"call_id","started_at","raw_agent","other_parties","skill","service","switch_call_id"} | 7 days | Source of truth ingest |
| calls.enriched | 12 | call_id | {"call_id","started_at","agent_id","skill","service","metadata_version"} | 7 days | Idempotent transform |
| audio.ready | 24 | call_id | {"call_id","s3_key","sha256","duration","sample_rate","ingest_delay_ms"} | 14 days | Drives scoring |
| scoring.results | 24 | call_id | {"call_id","score","model_version","latency_ms","breakdown"} | 30 days | For consumers / dashboards |

### 4.2 Serialization
- Sử dụng JSON ban đầu; khi throughput tăng chuyển sang Avro/Schema Registry để versioning.
- Compression: lz4.
- Idempotency: value có trường `event_ts` + `ingest_uuid`.

### 4.3 Error / DLQ Topics
- calls.raw.dlq
- audio.ready.dlq
- scoring.results.dlq
Mỗi message thêm `error_type`, `stack`, `retries`.

## 5. S3 Layout
```
s3://call-audio-bucket/
  raw/2025/09/12/123456789012345.wav
  processed/2025/09/12/123456789012345.flac
  transcripts/2025/09/12/123456789012345.json
```
- Server-side encryption (SSE-S3 hoặc KMS): bắt buộc.
- Lifecycle: raw > 90 ngày chuyển Glacier.
- Tagging: call_id, agent_id, date.
- Object metadata: checksum, codec, duration.

### 5.1 Naming Convention
- Bucket: `ccas-audio-${env}` (dev/stg/prod)
- Key pattern: `raw/{yyyy}/{mm}/{dd}/{call_id}.wav`
- Processed: `processed/{yyyy}/{mm}/{dd}/{call_id}_{model_version}.flac`
- Transcript: `transcripts/{yyyy}/{mm}/{dd}/{call_id}_{asr_model}.json`

### 5.2 Lifecycle Policies
- raw/: 90d -> Glacier, 365d -> delete
- processed/: 180d -> Glacier Deep Archive
- transcripts/: retain 365d (subject to compliance)

### 5.3 Security
- Block public access
- SSE-KMS (CMK) + bucket policy deny if not encrypted
- Versioning ON (đề phòng overwrite)
- Object Lock (Legal Hold) optional nếu compliance yêu cầu

### 5.4 Observability
- S3 Server Access Logs -> centralized bucket
- Event notifications (S3 -> EventBridge) nếu cần trigger re-score khi file updated

## 6. Database Schema (PostgreSQL)
```
TABLE call (
  id BIGSERIAL PK,
  call_id VARCHAR(32) UNIQUE NOT NULL,
  started_at TIMESTAMP NOT NULL,
  agent_id VARCHAR(16),
  customer_id VARCHAR(32),
  skill VARCHAR(64),
  status VARCHAR(32) NOT NULL, -- PENDING_DOWNLOAD | DOWNLOADED | SCORED | ERROR
  created_at TIMESTAMP DEFAULT now(),
  updated_at TIMESTAMP DEFAULT now()
);

TABLE audio_asset (
  id BIGSERIAL PK,
  call_id VARCHAR(32) REFERENCES call(call_id) ON DELETE CASCADE,
  s3_key TEXT NOT NULL,
  sha256 CHAR(64) NOT NULL,
  codec VARCHAR(16),
  sample_rate INT,
  duration_seconds NUMERIC(10,2),
  size_bytes BIGINT,
  status VARCHAR(16) NOT NULL, -- READY | MISSING | ERROR
  created_at TIMESTAMP DEFAULT now()
);

TABLE scoring_result (
  id BIGSERIAL PK,
  call_id VARCHAR(32) REFERENCES call(call_id) ON DELETE CASCADE,
  score NUMERIC(5,2) NOT NULL,
  model_version VARCHAR(32),
  details JSONB,
  latency_ms INT,
  created_at TIMESTAMP DEFAULT now()
);

TABLE ingestion_checkpoint (
  id INT PRIMARY KEY DEFAULT 1,
  last_polled_from TIMESTAMP NOT NULL,
  last_polled_to TIMESTAMP NOT NULL,
  updated_at TIMESTAMP DEFAULT now()
);

CREATE UNIQUE INDEX uq_audio_asset_call ON audio_asset(call_id);
CREATE INDEX idx_call_status ON call(status);
CREATE INDEX idx_scoring_result_created ON scoring_result(created_at);
```

### 6.1 Bảng agent (tuỳ chọn nếu cần enrich)
```
TABLE agent (
  id BIGSERIAL PK,
  agent_id VARCHAR(16) UNIQUE NOT NULL,
  full_name TEXT,
  team VARCHAR(64),
  hire_date DATE,
  active BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT now(),
  updated_at TIMESTAMP DEFAULT now()
);
```

### 6.2 Lý do thiết kế
- Tách `audio_asset` để dễ tái xử lý nếu file lỗi / re-download.
- `scoring_result` tách rời cho phép đa phiên bản model (many rows / call nếu cần) với unique `(call_id, model_version)`.
- `ingestion_checkpoint` đơn bản ghi để dễ cập nhật atomic (UPSERT id=1).

### 6.3 Migration Strategy
- Sử dụng Alembic (versioned migrations).
- Tên file: `YYYYMMDDHHMM_add_initial_tables.py`.
- Zero-downtime: thêm cột mới -> backfill -> tạo chỉ mục -> swap.

## 7. Chiến lược Latency & Concurrency
- Sliding window polling tránh race với cuộc gọi đang diễn ra.
- Async HTTP (httpx / aiohttp) + bounded semaphore (ví dụ 32 concurrent downloads).
- Backpressure: nếu lag > X phút, tạm giảm concurrency hoặc mở rộng thêm worker.
- Idempotency: Upsert bằng call_id; Kafka consumer offset commit only sau khi transaction DB + (S3 upload) thành công.
- Prefetch / pipelining: scoring worker bắt đầu load audio stream và gửi sang scoring service streaming.
- Partition key = call_id đảm bảo ordering per call (không quá quan trọng) nhưng phân phối đều với hash.
- Use compression (lz4 / snappy) cho payload metadata.

### 7.1 Tối ưu thêm
- Warm connection pools (HTTP keep-alive, reuse TLS sessions)
- Adaptive concurrency: đo p95 download latency, tăng/giảm semaphore bằng PID controller đơn giản
- Batch scoring (nếu model hỗ trợ) cho các file < N giây gộp chung
- Early termination: nếu audio < threshold (silent) bỏ qua scoring
- Caching model in memory + pin CPU affinity cho worker nóng
- Pre-fetch offsets: consumer poll lấy nhiều message (max.poll.records=500) rồi schedule tasks vào event loop

### 7.2 Công thức ước lượng throughput
Throughput ≈ (concurrency_download / avg_download_latency) * (success_rate) bị giới hạn bởi scoring_rate.

## 8. Trình tự (Sequence Flow)
1. Scheduler polls Avaya (T-90s..T-30s)
2. Parse XML -> list(call)
3. Dedup -> produce Kafka `calls.raw`
4. Enricher consume -> normalize -> DB upsert -> produce `calls.enriched`
5. Downloader consume -> parallel fetch replay -> S3 upload -> DB update audio_asset -> produce `audio.ready`
6. Scoring worker consume -> call scoring API -> DB insert scoring_result & update call.status= SCORED -> produce `scoring.results`
7. Exporter -> analytics store

### 8.1 Trạng thái & chuyển đổi
PENDING_DOWNLOAD -> DOWNLOADED -> SCORED
ERROR có thể quay lại PENDING_DOWNLOAD nếu retry policy còn.

### 8.2 Retry Policy
- Download: exponential backoff (1s,2s,4s,8s, max 5 attempts) -> DLQ
- Scoring: retry 3 lần với jitter nếu lỗi 5xx, lỗi 4xx -> DLQ ngay

### 8.3 Idempotent Handling
- Upsert bằng call_id (ON CONFLICT DO UPDATE minimal fields)
- Kafka offset commit sau khi DB transaction + S3 thành công

### 8.4 Dead Letter Flow
DLQ Consumer sẽ:
1. Ghi log + metrics
2. Cho phép requeue thủ công (REST endpoint) -> produce lại topic gốc

## 9. Metrics quan trọng
- ingest_delay = now - call.started_at (khi event vào `audio.ready`)
- scoring_total_latency = now - call.started_at (khi scored)
- scoring_service_latency (HTTP roundtrip)
- download_latency
- kafka_consumer_lag(topic, group)

## 10. Bảo mật & Tuân thủ
- Mã hoá in transit (HTTPS internal or mTLS)
- At-rest encryption (S3 + encrypted vols cho DB)
- Audit log access S3 / scoring results
- PII minimization: tách table chứa thông tin khách hàng nếu cần mã hoá cột.

## 11. Khả năng mở rộng
- Tăng partitions (calls.raw, audio.ready) để scale linear.
- Stateless workers (Kubernetes HPA dựa trên lag metrics).
- Sharded Postgres hoặc chuyển OLAP sang ClickHouse.

## 12. Roadmap mở rộng
- Thêm transcript (ASR) -> sentiment -> composite score.
- Feature store cho agent historical performance.
- Re-score khi model update (event `model.version.updated`).

## 13. Chạy thử local (Demo)
1. Khởi tạo hạ tầng:
```
docker compose up -d kafka zookeeper postgres minio create-bucket
```
2. Tạo file `.env` dựa trên `.env.example`.
3. Cài dependencies & migration:
```
pip install -r requirements.txt
alembic upgrade head
```
4. Chạy Avaya mock:
```
uvicorn Avaya.main:app --port 8000
```
5. Chạy ingestion + enricher + downloader + scoring:
```
python -m app.services.ingestion_scheduler
python -m app.services.metadata_enricher
python -m app.services.audio_downloader
python -m app.services.scoring_consumer
```
6. Metrics:
- Ingestion: http://localhost:9100/metrics
- Downloader: http://localhost:9200/metrics
7. Kiểm tra MinIO console: http://localhost:9001 (user: minio / pass: minio123)

### DLQ Topics
- audio.ready.dlq
- scoring.results.dlq
Consumer chuyên dụng có thể đọc và re-publish.

### Retry
- Downloader: exponential backoff 5 attempts
- Scoring: 3 attempts

---
Phần tiếp theo: thêm code skeleton services.
