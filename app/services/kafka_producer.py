from confluent_kafka import Producer
from app.common.config import settings

_producer = None

def get_producer() -> Producer:
    global _producer
    if _producer is None:
        _producer = Producer({'bootstrap.servers': settings.kafka_bootstrap})
    return _producer
