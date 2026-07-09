from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings

# For PostgreSQL database connections
connect_args = {}
if settings.DATABASE_URL.startswith("postgresql://") and "supabase" in settings.DATABASE_URL:
    # Add any specific SSL arguments if needed for Supabase in production
    pass

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args=connect_args
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
