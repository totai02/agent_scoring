from app.common.db import init_engine, Base
from app.common import models  # noqa: F401 ensure models imported

if __name__ == '__main__':
    engine = init_engine()
    Base.metadata.create_all(bind=engine)
    print("DB tables created")
