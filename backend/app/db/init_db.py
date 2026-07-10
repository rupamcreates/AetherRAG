import logging
from sqlalchemy import text
from app.db.session import engine, Base
# Import models to ensure they are registered with Base metadata
from app.db.models import Document, DocumentChunk, ChatThread

logger = logging.getLogger(__name__)

def init_db() -> None:
    logger.info("Initializing database...")
    try:
        with engine.begin() as conn:
            # Enable pgvector extension
            logger.info("Creating pgvector extension if not exists...")
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            
            # Create tables
            logger.info("Creating database tables...")
            Base.metadata.create_all(bind=conn)
            
            # Create HNSW index for vector column in document_chunks table to optimize semantic searches
            logger.info("Creating HNSW index on document_chunks table...")
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS document_chunks_hnsw_idx "
                "ON document_chunks "
                "USING hnsw (embedding vector_cosine_ops);"
            ))
            
            logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise e
