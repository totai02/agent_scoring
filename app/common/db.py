"""
Database Connection Management

This module provides database connection setup and session management
for the AgentScoring STT pipeline system using SQLAlchemy.

The module implements a singleton pattern for the database engine
and provides session factory functions.

Author: AgentScoring Team
Date: 2025-09-15
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.common.config import settings


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models.
    
    All model classes inherit from this base to provide
    consistent metadata and configuration.
    """
    pass


# Global database connection objects
_engine = None
_SessionLocal = None


def init_engine():
    """
    Initialize the database engine and session factory.
    
    Creates a singleton database engine with connection pooling
    and session factory configured for the application.
    
    Returns:
        sqlalchemy.Engine: The database engine instance
        
    Raises:
        RuntimeError: If DATABASE_URL is not configured
    """
    global _engine, _SessionLocal
    
    if _engine is None:
        if not settings.database_url:
            raise RuntimeError(
                "DATABASE_URL not configured. Please set the database_url "
                "in your .env file or environment variables."
            )
        
        # Create engine with connection health checks
        _engine = create_engine(
            settings.database_url, 
            pool_pre_ping=True,
            echo=False  # Set to True for SQL logging in development
        )
        
        # Create session factory
        _SessionLocal = sessionmaker(
            bind=_engine, 
            expire_on_commit=False
        )
    
    return _engine


def get_session():
    """
    Get a new database session.
    
    Creates a new database session for performing database operations.
    The session should be closed after use or used in a context manager.
    
    Returns:
        sqlalchemy.orm.Session: A new database session
        
    Example:
        session = get_session()
        try:
            # Perform database operations
            result = session.query(Call).all()
        finally:
            session.close()
    """
    if _SessionLocal is None:
        init_engine()
    return _SessionLocal()
