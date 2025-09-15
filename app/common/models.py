"""
SQLAlchemy Database Models

This module defines the database schema for the AgentScoring STT pipeline
system. It includes models for calls, audio assets, transcript segments,
agents, and processing checkpoints.

Author: AgentScoring Team
Date: 2025-09-15
"""

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, ForeignKey,
    Integer, Numeric, String, Text
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.common.db import Base


class Call(Base):
    """
    Represents a call in the system.
    
    Tracks the lifecycle of a call from initial ingestion through
    audio processing to final transcript completion.
    """
    __tablename__ = 'call'
    
    # Primary fields
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    call_id = Column(String(32), unique=True, nullable=False)
    started_at = Column(DateTime, nullable=False)
    
    # Metadata fields
    agent_id = Column(String(16))
    customer_id = Column(String(32))
    skill = Column(String(64))
    
    # Processing status tracking
    status = Column(
        String(32), 
        nullable=False, 
        default='PENDING_DOWNLOAD',
        comment='Current processing status: PENDING_DOWNLOAD, AUDIO_READY, COMPLETED'
    )
    processed_at = Column(
        DateTime,
        comment='Timestamp when STT processing completed'
    )
    
    # Audit fields
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(
        DateTime, 
        server_default=func.now(), 
        onupdate=func.now()
    )
    
    # Relationships
    audio_asset = relationship(
        'AudioAsset', 
        uselist=False, 
        back_populates='call'
    )
    transcript_segments = relationship(
        'TranscriptSegment', 
        back_populates='call'
    )


class AudioAsset(Base):
    """
    Represents an audio file associated with a call.
    
    Stores metadata about audio files uploaded to S3 storage,
    including file integrity information and processing status.
    """
    __tablename__ = 'audio_asset'
    
    # Primary fields
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    call_id = Column(
        String(32), 
        ForeignKey('call.call_id', ondelete='CASCADE')
    )
    
    # Storage metadata
    s3_key = Column(Text, nullable=False, comment='S3 object key')
    sha256 = Column(String(64), nullable=False, comment='File integrity hash')
    
    # Audio metadata
    codec = Column(String(16))
    sample_rate = Column(Integer)
    duration_seconds = Column(Numeric(10, 2))
    size_bytes = Column(BigInteger)
    
    # Processing status
    status = Column(
        String(16), 
        nullable=False, 
        default='READY',
        comment='Asset processing status'
    )
    
    # Audit fields
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    call = relationship('Call', back_populates='audio_asset')


class TranscriptSegment(Base):
    """
    Represents a single segment of transcribed speech.
    
    Each segment contains text, timing information, and optional
    speaker identification from the STT processing.
    """
    __tablename__ = "transcript_segments"
    
    # Primary fields
    id = Column(Integer, primary_key=True, index=True)
    call_id = Column(
        String, 
        ForeignKey("call.call_id"), 
        nullable=False, 
        index=True
    )
    
    # Speech segment data
    speaker = Column(
        String, 
        nullable=True, 
        index=True,
        comment='Speaker identification (if available)'
    )
    start_time = Column(
        Float, 
        nullable=False,
        comment='Segment start time in seconds'
    )
    end_time = Column(
        Float, 
        nullable=False,
        comment='Segment end time in seconds'
    )
    text = Column(
        Text, 
        nullable=False,
        comment='Transcribed text content'
    )
    
    # Audit fields
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    call = relationship("Call", back_populates='transcript_segments')


class Agent(Base):
    """
    Represents a call center agent.
    
    Stores agent information for linking with calls and
    performance analysis.
    """
    __tablename__ = 'agent'
    
    # Primary fields
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    agent_id = Column(String(16), unique=True, nullable=False)
    
    # Agent information
    full_name = Column(Text)
    team = Column(String(64))
    hire_date = Column(DateTime)
    active = Column(Boolean, default=True)
    
    # Audit fields
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(
        DateTime, 
        server_default=func.now(), 
        onupdate=func.now()
    )


class IngestionCheckpoint(Base):
    """
    Tracks ingestion progress for data polling.
    
    Maintains state about the last successfully processed
    time window to ensure no data is missed or duplicated.
    """
    __tablename__ = 'ingestion_checkpoint'
    
    # Primary fields
    id = Column(Integer, primary_key=True)
    
    # Checkpoint data
    last_polled_from = Column(
        DateTime, 
        nullable=False,
        comment='Start of last processed time window'
    )
    last_polled_to = Column(
        DateTime, 
        nullable=False,
        comment='End of last processed time window'
    )
    
    # Audit fields
    updated_at = Column(
        DateTime, 
        server_default=func.now(), 
        onupdate=func.now()
    )
