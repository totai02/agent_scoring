# Speech-to-Text Pipeline for Call Center Recordings

Hệ thống xử lý và phiên âm (transcribe) các cuộc gọi ghi âm từ tổng đài, xây dựng với các thành phần: Avaya API (nguồn), Kafka (event backbone), S3 (lưu trữ audio), Database (lưu metadata và kết quả phiên âm), và một service Speech-to-Text (STT) sử dụng mô hình Whisper.

## 1. Mục tiêu
- Ingest audio gần như real-time sau khi cuộc gọi kết thúc.
- Tối ưu độ trễ, thực hiện phiên âm song song.
- Lưu trữ kết quả phiên âm chi tiết bao gồm người nói, nội dung và dấu thời gian.
- Dễ dàng mở rộng hệ thống khi tải tăng.

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
                             (A) Metadata Enricher      (B) Audio Downloader         (C) STT Consumer
                                    |                          |                           |
                                    v                          v                           v
                              Kafka calls.enriched     S3 put object (audio)        Lưu kết quả vào DB
                                    |                          |
                                    +-----------+--------------+
                                                |
                                                v
                                         PostgreSQL
                                          (calls, audio_asset, transcript_segments)
```

## 3. Các service chính
1. **Ingestion Scheduler / Poller**: Định kỳ lấy thông tin các cuộc gọi mới từ Avaya API và đưa vào Kafka topic `calls.raw`.
2. **Metadata Enricher**: Xử lý thông tin thô, chuẩn hóa và lưu vào bảng `calls` trong database, sau đó đẩy tin nhắn vào topic `calls.enriched`.
3. **Audio Downloader Worker**: Lắng nghe topic `calls.enriched`, tải file ghi âm tương ứng, lưu vào S3 (MinIO), và thông báo qua topic `audio.ready`.
4. **STT (Speech-to-Text) Consumer**: Lắng nghe topic `audio.ready`, tải file âm thanh từ S3, sử dụng mô hình `faster-whisper` để phiên âm và phân tách người nói. Kết quả cuối cùng được lưu vào bảng `transcript_segments` trong database.

## 4. Kafka Topics & Schema
- **calls.raw**: Chứa thông tin cuộc gọi thô từ Avaya.
- **calls.enriched**: Thông tin cuộc gọi đã được chuẩn hóa.
- **audio.ready**: Thông báo file ghi âm đã sẵn sàng trên S3 để xử lý.
- **DLQ topics**: Các topic để chứa các tin nhắn xử lý lỗi.

## 5. S3 Layout
- `s3://ccas-audio-dev/raw/yyyy/mm/dd/call_id.wav`: Lưu trữ các file ghi âm gốc.

## 6. Database Schema (PostgreSQL)
Bao gồm các bảng chính:
- `calls`: Lưu thông tin metadata của cuộc gọi.
- `audio_assets`: Lưu thông tin về file ghi âm trên S3.
- `ingestion_checkpoints`: Theo dõi tiến trình lấy dữ liệu.
- `transcript_segments`: **Bảng mới** để lưu kết quả phiên âm chi tiết.
  ```sql
  TABLE transcript_segments (
    id SERIAL PRIMARY KEY,
    call_id VARCHAR(255) REFERENCES calls(id),
    speaker VARCHAR(255),
    start_time FLOAT,
    end_time FLOAT,
    text TEXT,
    created_at TIMESTAMP
  );
  ```

## 7. Chạy thử local
1.  **Khởi tạo hạ tầng:**
    ```bash
    docker compose up -d
    ```
2.  **Cài đặt dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
3.  **Áp dụng Database Migrations:**
    Hệ thống sử dụng Alembic để quản lý schema. Chạy lệnh sau để cập nhật database với bảng `transcript_segments` mới:
    ```bash
    docker compose exec metadata-enricher alembic upgrade head
    ```
4.  **Chạy các services:**
    Sau khi hạ tầng và database đã sẵn sàng, bạn có thể khởi chạy toàn bộ hệ thống bằng một lệnh duy nhất đã được cấu hình trong `docker-compose.yml`. Các service (ingestion, downloader, stt-consumer,...) sẽ tự động chạy.

5.  **Kiểm tra kết quả:**
    - **MinIO Console**: Truy cập `http://localhost:9001` để xem các file audio đã được tải lên.
    - **Database**: Kết nối vào PostgreSQL để xem dữ liệu trong các bảng `calls` và `transcript_segments`.
    - **Logs**: Theo dõi logs từ các container để xem tiến trình xử lý: `docker compose logs -f stt-consumer`.

## 8. Kết nối Database
**PostgreSQL Connection Info:**

Từ máy host (localhost):
```
Host: localhost
Port: 5432
Database: agent_scoring
Username: agent
Password: agentpw
Connection URL: postgresql://agent:agentpw@localhost:5432/agent_scoring
```

Từ bên trong Docker network:
```
Host: postgres
Port: 5432
Database: agent_scoring
Username: agent
Password: agentpw
Connection URL: postgresql://agent:agentpw@postgres:5432/agent_scoring
```

**Tools để kết nối:**
- pgAdmin: Công cụ GUI để quản lý PostgreSQL
- DBeaver: Universal database tool
- psql: Command line tool
- VS Code với PostgreSQL extension

