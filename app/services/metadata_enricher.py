import asyncio
import json
from confluent_kafka import Consumer
from app.common.config import settings
from app.common.db import get_session, init_engine
from app.common.models import Call
from .kafka_producer import get_producer
from datetime import datetime


def parse_agent(raw_agent: str | None) -> str | None:
    if not raw_agent:
        return None
    # Format: "2665 (agent2801.247)" -> extract "2801"
    if 'agent' in raw_agent:
        # Find the part in parentheses
        import re
        match = re.search(r'agent(\d+)', raw_agent)
        if match:
            return match.group(1)
    return None

async def run_enricher():
    init_engine()
    consumer = Consumer({
        'bootstrap.servers': settings.kafka_bootstrap,
        'group.id': 'enricher-group',
        'auto.offset.reset': 'earliest'
    })
    consumer.subscribe([settings.topic_calls_raw])
    producer = get_producer()

    while True:
        msg = consumer.poll(0.2)
        if msg is None:
            await asyncio.sleep(0.05)
            continue
        if msg.error():
            print(f"[enricher][err]{msg.error()}")
            continue
        data = json.loads(msg.value())
        call_id = data['call_id']
        started_at = datetime.fromisoformat(data['started_at']) if 'started_at' in data else datetime.utcnow()
        agent_id = parse_agent(data.get('raw_agent'))
        with get_session() as sess:
            existing = sess.query(Call).filter_by(call_id=call_id).one_or_none()
            if existing is None:
                c = Call(call_id=call_id, started_at=started_at, agent_id=agent_id, status='PENDING_DOWNLOAD')
                sess.add(c)
            sess.commit()
        enriched_payload = {
            'call_id': call_id,
            'started_at': started_at.isoformat(),
            'agent_id': agent_id
        }
        producer.produce(settings.topic_calls_enriched, key=call_id, value=json.dumps(enriched_payload))

if __name__ == '__main__':
    asyncio.run(run_enricher())
