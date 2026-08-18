from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy import create_engine
import os
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DB_URL")
if not DB_URL:
    raise RuntimeError("DB_URL environment variable is not set. Check your .env file.")

engine = create_engine(
    DB_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()