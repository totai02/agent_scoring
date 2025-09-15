from sqlalchemy import Column, BigInteger, String, DateTime, Numeric, Integer, JSON, Text, Boolean, ForeignKey, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.common.db import Base

class Call(Base):
    __tablename__ = 'call'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    call_id = Column(String(32), unique=True, nullable=False)
    started_at = Column(DateTime, nullable=False)
    agent_id = Column(String(16))
    customer_id = Column(String(32))
    skill = Column(String(64))
    status = Column(String(32), nullable=False, default='PENDING_DOWNLOAD')
    processed_at = Column(DateTime)  # Timestamp when STT processing completed
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    audio_asset = relationship('AudioAsset', uselist=False, back_populates='call')
    transcript_segments = relationship('TranscriptSegment', back_populates='call')

class AudioAsset(Base):
    __tablename__ = 'audio_asset'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    call_id = Column(String(32), ForeignKey('call.call_id', ondelete='CASCADE'))
    s3_key = Column(Text, nullable=False)
    sha256 = Column(String(64), nullable=False)
    codec = Column(String(16))
    sample_rate = Column(Integer)
    duration_seconds = Column(Numeric(10,2))
    size_bytes = Column(BigInteger)
    status = Column(String(16), nullable=False, default='READY')
    created_at = Column(DateTime, server_default=func.now())
    call = relationship('Call', back_populates='audio_asset')

class IngestionCheckpoint(Base):
    __tablename__ = 'ingestion_checkpoint'
    id = Column(Integer, primary_key=True)
    last_polled_from = Column(DateTime, nullable=False)
    last_polled_to = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class Agent(Base):
    __tablename__ = 'agent'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    agent_id = Column(String(16), unique=True, nullable=False)
    full_name = Column(Text)
    team = Column(String(64))
    hire_date = Column(DateTime)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id = Column(Integer, primary_key=True, index=True)
    call_id = Column(String, ForeignKey("call.call_id"), nullable=False, index=True)
    speaker = Column(String, nullable=True, index=True)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    call = relationship("Call", back_populates='transcript_segments')
