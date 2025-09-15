"""
Call Ingestion Scheduler Service

This module provides automated polling and ingestion of call data from the
Avaya system API. It periodically queries for new calls within time windows
and publishes them to Kafka for downstream processing.

The service implements:
- Time-windowed polling with configurable intervals
- XML response parsing for call metadata extraction
- Kafka message production for call events
- Prometheus metrics for monitoring
- Error handling and retry logic

Author: AgentScoring Team
Date: 2025-09-15
"""

import asyncio
import datetime as dt
import json
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

import httpx
from prometheus_client import Counter, Histogram, start_http_server

from app.common.config import settings
from .kafka_producer import get_producer


# Global checkpoint tracking (replace with DB persistence in production)
_last_polled_to: Optional[dt.datetime] = None

# Prometheus metrics
INGEST_CALLS = Counter('ingest_calls_total', 'Total calls ingested')
INGEST_WINDOW_SECONDS = Histogram(
    'ingest_window_span_seconds', 
    'Time span in seconds of each poll window'
)


async def poll_once() -> Tuple[int, dt.datetime, dt.datetime]:
    """
    Poll the Avaya API once for new calls within a time window.
    
    Queries the Avaya search API for calls within a calculated time window,
    parses the XML response, and publishes call events to Kafka.
    
    Returns:
        Tuple[int, datetime, datetime]: Count of calls processed, window start, window end
        
    Raises:
        httpx.HTTPError: If API request fails
        ET.ParseError: If XML parsing fails
    """
    global _last_polled_to
    
    # Calculate polling time window
    now = dt.datetime.utcnow()
    window_len = dt.timedelta(seconds=settings.poll_window_seconds)
    delay = dt.timedelta(seconds=settings.poll_delay_seconds)
    target_end = now - delay
    
    if _last_polled_to is None:
        # First run: use full window
        target_start = target_end - window_len
    else:
        # Subsequent runs: continue from last position
        target_start = _last_polled_to
    
    # Remove microseconds for cleaner API calls
    target_start = target_start.replace(microsecond=0)
    target_end = target_end.replace(microsecond=0)

    def format_datetime(dt_obj: dt.datetime) -> str:
        """Format datetime for Avaya API."""
        return dt_obj.strftime("%d/%m/%y %H:%M:%S")

    # Prepare API parameters
    start_date, start_time = format_datetime(target_start).split(" ")
    end_date, end_time = format_datetime(target_end).split(" ")

    params = {
        "command": "search",
        "layout": "SearchLayout60",
        "param1_startedat": start_date,
        "param2_startedat": start_time,
        "param3_startedat": end_date,
        "param4_startedat": end_time,
        "operator_startedat": "9",  # Between operator
    }

    # Query Avaya API
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{settings.avaya_base_url}/searchapi", 
            params=params
        )
        response.raise_for_status()
        xml_text = response.text

    # Parse XML response
    root = ET.fromstring(xml_text)
    
    # Process and publish call events
    producer = get_producer()
    count = 0
    
    for result in root.findall('result'):
        # Extract required fields
        call_id_field = result.find(".//field[@name='inums']")
        started_field = result.find(".//field[@name='startedat']")
        agents_field = result.find(".//field[@name='agents']")
        
        # Skip incomplete records
        if call_id_field is None or started_field is None:
            continue
        
        # Extract field values
        call_id = call_id_field.text.strip()
        started_at = started_field.text.strip()
        raw_agent = agents_field.text.strip() if agents_field is not None else None
        
        # Prepare message payload
        payload = {
            "call_id": call_id,
            "started_at": started_at,
            "raw_agent": raw_agent,
        }
        
        # Publish to Kafka
        producer.produce(
            settings.topic_calls_raw,
            key=call_id,
            value=json.dumps(payload)
        )
        count += 1
    
    # Ensure all messages are sent
    producer.flush()
    
    # Update checkpoint
    _last_polled_to = target_end
    
    # Record metrics
    INGEST_CALLS.inc(count)
    INGEST_WINDOW_SECONDS.observe((target_end - target_start).total_seconds())
    
    return count, target_start, target_end


async def run_scheduler() -> None:
    """
    Run the continuous ingestion scheduler.
    
    Starts the Prometheus metrics server and runs the polling loop
    indefinitely with error handling and configurable intervals.
    """
    # Start Prometheus metrics server
    start_http_server(9100)
    print("[ingestion] Prometheus metrics server started on port 9100")
    
    while True:
        try:
            count, start_time, end_time = await poll_once()
            print(
                f"[ingestion] Processed {count} calls for window "
                f"{start_time} -> {end_time}"
            )
        except Exception as ex:
            print(f"[ingestion][error] Failed to poll: {ex}")
        
        # Wait before next poll
        await asyncio.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":
    asyncio.run(run_scheduler())
