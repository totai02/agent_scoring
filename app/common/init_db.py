"""
Database Initialization Script

This module provides database table creation functionality for the
AgentScoring STT pipeline system. It creates all tables defined
in the models module.

Usage:
    python -m app.common.init_db

Author: AgentScoring Team
Date: 2025-09-15
"""

from app.common.db import Base, init_engine
from app.common import models  # noqa: F401 - Import needed to register models


def create_tables():
    """
    Create all database tables.
    
    Creates all tables defined in the models module using
    SQLAlchemy's metadata.create_all() method.
    
    Returns:
        None
    """
    engine = init_engine()
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully")


if __name__ == '__main__':
    create_tables()
