# Call Tracking với Redis

## Tổng quan

Hệ thống call tracking được thiết kế để giải quyết vấn đề **bỏ qua call** trong ingestion scheduler. Vấn đề xảy ra khi:

- Một call bắt đầu trong khoảng thời gian quét hiện tại
- Nhưng call đó chưa kết thúc khi polling window kế tiếp bắt đầu
- Dẫn đến call bị process nhiều lần hoặc bị bỏ qua

## Giải pháp

Sử dụng **Redis** với **TTL (Time To Live)** để track các call đang được xử lý:

1. **Tracking mechanism**: Mỗi call được đánh dấu trong Redis với TTL
2. **Duplicate prevention**: Filter out các call đã được track
3. **Automatic cleanup**: TTL tự động xóa entries hết hạn
4. **Fallback handling**: Graceful fallback khi Redis không available

## Cấu hình

### Environment Variables

Thêm các biến sau vào `.env`:

```bash
# Redis configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=  # Optional
CALL_TRACKING_TTL_SECONDS=3600  # 1 hour TTL
```

### Dependencies

Redis dependency đã được thêm vào `requirements.txt`:

```
redis>=5.0.0
```

## Cách hoạt động

### 1. Ingestion Scheduler Flow

```
1. Poll Avaya API → Get calls in time window
2. Extract call IDs → Filter tracked calls via Redis
3. Skip tracked calls → Process only new calls  
4. Mark new calls as tracked → Publish to Kafka
5. TTL automatically expires old entries
```

### 2. Redis Key Structure

```
Key: call:tracking:{call_id}
Value: "processing"  
TTL: 3600 seconds (configurable)
```

### 3. Metrics

Prometheus metrics được thêm:

- `ingest_calls_total`: Tổng số call đã xử lý
- `ingest_calls_skipped_total`: Số call bị skip do đã track
- `ingest_window_span_seconds`: Thời gian window polling

## Sử dụng

### Chạy Ingestion Scheduler

```bash
# Normal mode
python -m app.services.ingestion_scheduler

# Cleanup mode  
python -m app.services.ingestion_scheduler cleanup
```

### Monitor Call Tracking

Sử dụng script monitor để theo dõi:

```bash
# Xem thống kê
python call_tracking_monitor.py stats

# List các call đang được track
python call_tracking_monitor.py list

# Cleanup tất cả tracking entries
python call_tracking_monitor.py cleanup

# Test Redis connection
python call_tracking_monitor.py test
```

## Error Handling

### Redis Unavailable

- System tiếp tục hoạt động bình thường
- Log warning messages
- Không block call processing
- Graceful degradation

### Connection Issues

- Automatic reconnection với retry logic
- Connection pooling
- Timeout configuration
- Circuit breaker pattern

## Performance Considerations

### Redis Operations

- **Batch filtering**: Sử dụng pipeline cho multiple checks
- **Connection pooling**: Reuse connections
- **Async operations**: Non-blocking Redis calls
- **TTL cleanup**: Automatic memory management

### Memory Usage

- TTL prevents memory leaks
- Key pattern: `call:tracking:*`
- Estimated memory: ~100 bytes per tracked call
- With 1000 concurrent calls: ~100KB

## Troubleshooting

### Check Redis Status

```bash
# Test connection
python call_tracking_monitor.py test

# View stats
python call_tracking_monitor.py stats
```

### Common Issues

1. **Redis connection failed**
   - Check Redis server running
   - Verify connection config
   - Check network connectivity

2. **High memory usage**
   - Check TTL settings
   - Monitor tracked calls count
   - Consider shorter TTL

3. **Calls still duplicated**
   - Verify Redis is working
   - Check TTL expiration
   - Monitor skip metrics

### Logs

Monitor ingestion scheduler logs for:

```
[ingestion] Skipped X calls already being tracked
[ingestion] Currently tracking X active calls  
[ingestion][warning] Redis unavailable, allowing call processing
```

## Production Deployment

### Redis Setup

```bash
# Docker Compose
redis:
  image: redis:7-alpine
  ports:
    - "6379:6379"
  volumes:
    - redis_data:/data
  command: redis-server --appendonly yes
```

### Monitoring

- Set up Redis monitoring (memory, connections)
- Alert on high tracking counts
- Monitor skip rates via Prometheus

### Scaling

- Redis supports multiple ingestion scheduler instances
- Shared tracking state across instances
- Consider Redis Cluster for high availability

## Migration Guide

### Từ version cũ

1. Update dependencies: `pip install -r requirements.txt`
2. Add Redis config to `.env`
3. Start Redis server
4. Deploy updated ingestion scheduler
5. Monitor metrics for correct behavior

### Rollback Plan

1. Stop new scheduler
2. Deploy old version (without Redis)
3. Redis tracking keys will expire naturally
4. No data loss risk

## API Reference

### CallTracker Class

```python
from app.common.redis_client import get_call_tracker

tracker = get_call_tracker()

# Check if call is tracked
is_tracked = await tracker.is_call_being_tracked("call_123")

# Start tracking call
success = await tracker.track_call("call_123", ttl_seconds=3600)

# Stop tracking call  
success = await tracker.untrack_call("call_123")

# Filter tracked calls
untracked = await tracker.filter_tracked_calls({"call_1", "call_2"})

# Get statistics
stats = await tracker.get_tracking_stats()
```

## Tài liệu tham khảo

- [Redis TTL Documentation](https://redis.io/commands/ttl)
- [Redis Pipeline](https://redis.io/docs/manual/pipelining/)
- [Prometheus Metrics](https://prometheus.io/docs/practices/naming/)