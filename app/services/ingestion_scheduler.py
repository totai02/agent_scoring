import asyncio
import datetime as dt
import httpx
import xml.etree.ElementTree as ET
import json
from .kafka_producer import get_producer
from app.common.config import settings
from prometheus_client import Counter, Histogram, start_http_server

# Simple in-memory checkpoint (replace with DB persistence)
_last_polled_to: dt.datetime | None = None

INGEST_CALLS = Counter('ingest_calls_total', 'Total calls ingested')
INGEST_WINDOW_SECONDS = Histogram('ingest_window_span_seconds', 'Span seconds of each poll window')

async def poll_once():
    global _last_polled_to
    now = dt.datetime.utcnow()
    window_len = dt.timedelta(seconds=settings.poll_window_seconds)
    delay = dt.timedelta(seconds=settings.poll_delay_seconds)
    target_end = now - delay
    if _last_polled_to is None:
        target_start = target_end - window_len
    else:
        target_start = _last_polled_to
    target_start = target_start.replace(microsecond=0)
    target_end = target_end.replace(microsecond=0)

    def fmt(d: dt.datetime):
        return d.strftime("%d/%m/%y %H:%M:%S")

    start_date, start_time = fmt(target_start).split(" ")
    end_date, end_time = fmt(target_end).split(" ")

    params = {
        "command": "search",
        "layout": "SearchLayout60",
        "param1_startedat": start_date,
        "param2_startedat": start_time,
        "param3_startedat": end_date,
        "param4_startedat": end_time,
        "operator_startedat": "9",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{settings.avaya_base_url}/searchapi", params=params)
        r.raise_for_status()
        xml_text = r.text

    root = ET.fromstring(xml_text)
    producer = get_producer()
    count = 0
    for result in root.findall('result'):
        call_id_field = result.find(".//field[@name='inums']")
        started_field = result.find(".//field[@name='startedat']")
        if call_id_field is None or started_field is None:
            continue
        call_id = call_id_field.text.strip()
        started_at = started_field.text.strip()
        payload = {
            "call_id": call_id,
            "started_at": started_at,
        }
        producer.produce(settings.topic_calls_raw, key=call_id, value=json.dumps(payload))
        count += 1
    producer.flush()
    _last_polled_to = target_end
    INGEST_CALLS.inc(count)
    INGEST_WINDOW_SECONDS.observe((target_end - target_start).total_seconds())
    return count, target_start, target_end

async def run_scheduler():
    start_http_server(9100)
    while True:
        try:
            count, s, e = await poll_once()
            print(f"[ingestion] emitted {count} calls window {s}->{e}")
        except Exception as ex:
            print(f"[ingestion][error] {ex}")
        await asyncio.sleep(settings.poll_interval_seconds)

if __name__ == "__main__":
    asyncio.run(run_scheduler())
