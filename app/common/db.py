from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.common.config import settings

class Base(DeclarativeBase):
    pass

_engine = None
_SessionLocal = None

def init_engine():
    global _engine, _SessionLocal
    if _engine is None:
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL not configured")
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine

def get_session():
    if _SessionLocal is None:
        init_engine()
    return _SessionLocal()
