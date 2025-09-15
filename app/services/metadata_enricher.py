"""
Metadata Enricher Service

This service consumes raw call messages from Kafka, enriches them with agent
information, stores call records in the database, and publishes enriched
messages for further processing.

Features:
- Agent ID extraction from Avaya format
- Call record persistence in database
- Message enrichment and forwarding

Author: AgentScoring Team
Date: 2025-09-15
"""

import asyncio
import json
import re
from datetime import datetime
from typing import Optional

from confluent_kafka import Consumer

from app.common.config import settings
from app.common.db import get_session, init_engine
from app.common.models import Call
from .kafka_producer import get_producer


def parse_agent(raw_agent: Optional[str]) -> Optional[str]:
    """
    Extract agent ID from Avaya format string.
    
    Converts format like "2665 (agent2801.247)" to "2801"
    
    Args:
        raw_agent: Raw agent string from Avaya system
        
    Returns:
        str: Extracted agent ID, or None if parsing fails
    """
    if not raw_agent:
        return None
        
    # Look for pattern "agent<digits>" in the string
    if 'agent' in raw_agent:
        match = re.search(r'agent(\d+)', raw_agent)
        if match:
            return match.group(1)
    
    return None


async def process_call_message(message_data: dict, producer) -> None:
    """
    Process a single call message.
    
    Args:
        message_data: Parsed message data from Kafka
        producer: Kafka producer instance
    """
    # Extract message fields
    call_id = message_data['call_id']
    started_at = (
        datetime.fromisoformat(message_data['started_at'])
        if 'started_at' in message_data
        else datetime.utcnow()
    )
    agent_id = parse_agent(message_data.get('raw_agent'))
    
    # Store call record in database
    with get_session() as db_session:
        existing_call = db_session.query(Call).filter_by(call_id=call_id).one_or_none()
        
        if existing_call is None:
            new_call = Call(
                call_id=call_id,
                started_at=started_at,
                agent_id=agent_id,
                status='PENDING_DOWNLOAD'
            )
            db_session.add(new_call)
            db_session.commit()
    
    # Create enriched message payload
    enriched_payload = {
        'call_id': call_id,
        'started_at': started_at.isoformat(),
        'agent_id': agent_id
    }
    
    # Publish enriched message
    producer.produce(
        settings.topic_calls_enriched,
        key=call_id,
        value=json.dumps(enriched_payload)
    )


async def run_enricher() -> None:
    """
    Main enricher service function.
    
    Consumes raw call messages, enriches them with metadata,
    and publishes enriched messages for downstream processing.
    """
    # Initialize database engine
    init_engine()
    
    # Configure Kafka consumer
    consumer = Consumer({
        'bootstrap.servers': settings.kafka_bootstrap,
        'group.id': 'enricher-group',
        'auto.offset.reset': 'earliest'
    })
    consumer.subscribe([settings.topic_calls_raw])
    
    # Initialize Kafka producer
    producer = get_producer()
    
    print("Metadata enricher started. Processing raw call messages...")
    
    while True:
        # Poll for new messages
        message = consumer.poll(0.2)
        
        if message is None:
            await asyncio.sleep(0.05)
            continue
            
        if message.error():
            print(f"[enricher][error] {message.error()}")
            continue
        
        try:
            # Parse and process message
            message_data = json.loads(message.value())
            await process_call_message(message_data, producer)
            
        except Exception as ex:
            print(f"[enricher][error] Failed to process message: {ex}")


if __name__ == '__main__':
    asyncio.run(run_enricher())
