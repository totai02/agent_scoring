import json
from confluent_kafka import Consumer
from app.common.config import settings
from .kafka_producer import get_producer

DLQ_TOPIC = 'scoring.results.dlq'
REQUEUE_TOPIC = 'audio.ready'  # hoặc topic gốc bạn muốn
MAX_RETRIES = 3  # đồng bộ với scoring_consumer.py

def requeue_message(producer, data):
    # Tăng số lần thử lại
    data['attempts'] = int(data.get('attempts', 0)) + 1
    producer.produce(REQUEUE_TOPIC, key=data.get('call_id', ''), value=json.dumps(data))
    producer.flush()
    print(f"[DLQ][auto-requeue] {data['call_id']} -> {REQUEUE_TOPIC} (attempts={data['attempts']})")

def run_dlq_consumer():
    consumer = Consumer({
        'bootstrap.servers': settings.kafka_bootstrap,
        'group.id': 'dlq-consumer-group',
        'auto.offset.reset': 'earliest'
    })
    consumer.subscribe([DLQ_TOPIC])
    producer = get_producer()
    print(f"Listening DLQ topic: {DLQ_TOPIC}")
    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            print(f"[DLQ][err]{msg.error()}")
            continue
        try:
            data = json.loads(msg.value())
            print(f"[DLQ] {data}")
            attempts = int(data.get('attempts', 0))
            if attempts < MAX_RETRIES:
                requeue_message(producer, data)
            else:
                print(f"[DLQ][skip] {data['call_id']} đã vượt quá số lần retry ({attempts})")
        except Exception as ex:
            print(f"[DLQ][parse error] {ex} raw: {msg.value()}")

if __name__ == '__main__':
    run_dlq_consumer()
