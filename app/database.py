import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

# default sqlite file in project root, override with env if needed
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./delivery.db")

_kw = {"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else {}
if DATABASE_URL.startswith("sqlite") and ":memory:" in DATABASE_URL:
    _kw["poolclass"] = StaticPool
engine = create_engine(DATABASE_URL, **_kw)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


@event.listens_for(engine, "connect")
def _sqlite_pragma(dbapi_conn, _connection_record):
    # need this for FK on driver delete
    if DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
