"""
Kafka Producer Management

This module provides a singleton Kafka producer instance for the
AgentScoring STT pipeline system. It manages the lifecycle of the
Kafka producer and provides a factory function for access.

The producer is configured with the bootstrap servers from the
application settings and reused across the application to maintain
connection efficiency.

Author: AgentScoring Team
Date: 2025-09-15
"""

from confluent_kafka import Producer

from app.common.config import settings


# Global producer instance
_producer = None


def get_producer() -> Producer:
    """
    Get a singleton Kafka producer instance.
    
    Creates and returns a Kafka producer configured with the
    bootstrap servers from application settings. The producer
    is created once and reused for efficiency.
    
    Returns:
        confluent_kafka.Producer: Configured Kafka producer instance
        
    Example:
        producer = get_producer()
        producer.produce('topic_name', key='key', value='message')
        producer.flush()  # Ensure message delivery
    """
    global _producer
    
    if _producer is None:
        _producer = Producer({
            'bootstrap.servers': settings.kafka_bootstrap,
            'client.id': 'agentscoring-producer',
            'retries': 5,
            'retry.backoff.ms': 100,
            'queue.buffering.max.ms': 100,  # Batch messages for efficiency
        })
    
    return _producer
