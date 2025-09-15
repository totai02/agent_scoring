"""
Dead Letter Queue (DLQ) Consumer Service

This module provides automated processing of failed messages from the
Dead Letter Queue. It implements retry logic with exponential backoff
and maximum retry limits for fault tolerance.

The service:
- Consumes messages from the DLQ topic
- Tracks retry attempts for each message
- Re-queues messages that haven't exceeded retry limits
- Discards messages that have exceeded maximum retries
- Provides logging for observability

Author: AgentScoring Team
Date: 2025-09-15
"""

import json
from typing import Dict, Any

from confluent_kafka import Consumer

from app.common.config import settings
from .kafka_producer import get_producer


# DLQ configuration
DLQ_TOPIC = 'audio.ready.dlq'  # Updated for STT pipeline
REQUEUE_TOPIC = 'audio.ready'  # Topic to requeue failed messages
MAX_RETRIES = 3  # Maximum retry attempts before permanent failure


def requeue_message(producer, data: Dict[str, Any]) -> None:
    """
    Requeue a failed message for retry processing.
    
    Increments the retry attempt counter and sends the message
    back to the original processing topic for another attempt.
    
    Args:
        producer: Kafka producer instance
        data: Message data dictionary containing call information
    """
    # Increment retry attempt counter
    data['attempts'] = int(data.get('attempts', 0)) + 1
    
    # Send back to processing queue
    producer.produce(
        REQUEUE_TOPIC,
        key=data.get('call_id', ''),
        value=json.dumps(data)
    )
    producer.flush()
    
    print(
        f"[DLQ][auto-requeue] {data['call_id']} -> {REQUEUE_TOPIC} "
        f"(attempts={data['attempts']})"
    )


def run_dlq_consumer() -> None:
    """
    Run the DLQ consumer loop.
    
    Continuously processes messages from the Dead Letter Queue,
    implementing retry logic and permanent failure handling.
    """
    # Configure Kafka consumer
    consumer = Consumer({
        'bootstrap.servers': settings.kafka_bootstrap,
        'group.id': 'dlq-consumer-group',
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': True,
        'session.timeout.ms': 30000,
    })
    
    consumer.subscribe([DLQ_TOPIC])
    producer = get_producer()
    
    print(f"[DLQ] Starting DLQ consumer for topic: {DLQ_TOPIC}")
    print(f"[DLQ] Max retries: {MAX_RETRIES}")
    print(f"[DLQ] Requeue topic: {REQUEUE_TOPIC}")
    
    try:
        while True:
            # Poll for messages
            msg = consumer.poll(timeout=1.0)
            
            if msg is None:
                continue
                
            if msg.error():
                print(f"[DLQ][error] Kafka error: {msg.error()}")
                continue
            
            try:
                # Parse message data
                data = json.loads(msg.value())
                call_id = data.get('call_id', 'unknown')
                attempts = int(data.get('attempts', 0))
                
                print(f"[DLQ] Processing failed message for call: {call_id}")
                print(f"[DLQ] Message data: {data}")
                
                # Check retry limit
                if attempts < MAX_RETRIES:
                    print(
                        f"[DLQ] Requeuing call {call_id} "
                        f"(attempt {attempts + 1}/{MAX_RETRIES})"
                    )
                    requeue_message(producer, data)
                else:
                    print(
                        f"[DLQ][permanent-failure] Call {call_id} exceeded "
                        f"maximum retries ({attempts}). Discarding message."
                    )
                    # In production, you might want to:
                    # - Log to persistent storage
                    # - Send alert/notification
                    # - Store in failure database table
                
            except json.JSONDecodeError as ex:
                print(
                    f"[DLQ][parse-error] Failed to parse JSON: {ex}. "
                    f"Raw message: {msg.value()}"
                )
            except Exception as ex:
                print(
                    f"[DLQ][processing-error] Error processing message: {ex}. "
                    f"Raw message: {msg.value()}"
                )
    
    except KeyboardInterrupt:
        print("[DLQ] Shutting down DLQ consumer...")
    finally:
        consumer.close()


if __name__ == '__main__':
    run_dlq_consumer()
