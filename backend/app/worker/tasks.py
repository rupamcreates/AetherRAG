import os
import uuid
import tempfile
import logging
from celery.utils.log import get_task_logger
from app.worker.celery_app import celery_app
from app.db.session import SessionLocal
from app.db.models import Document, DocumentChunk
from app.rag.parser import DocumentParser
from app.rag.chunker import DocumentChunker
from app.rag.embeddings import HuggingFaceInferenceEmbeddings
from app.services.storage import StorageService

logger = get_task_logger(__name__)

@celery_app.task(name="app.worker.tasks.process_document_task", bind=True, max_retries=2)
def process_document_task(self, document_id: str) -> bool:
    """
    Ingests and processes a document:
    1. Downloads file from storage.
    2. Parses layout and components.
    3. Chunks the contents recursively and semantically.
    4. Computes embeddings.
    5. Saves vectors and metadata to postgres/pgvector database.
    """
    logger.info(f"Starting ingestion process for document ID: {document_id}")
    db = SessionLocal()
    
    try:
        # 1. Fetch document from DB
        doc_uuid = uuid.UUID(document_id)
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if not doc:
            logger.error(f"Document {document_id} not found in database.")
            return False
        
        # Update status to processing
        doc.status = "processing"
        db.commit()
        
        # 2. Setup temporary file for parsing (safe for Windows file locking)
        suffix = os.path.splitext(doc.name)[1]
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"rag_{uuid.uuid4().hex}{suffix}")
            
        try:
            # Download file content to temp file
            storage = StorageService.get_storage()
            storage.download_file(doc.storage_path, temp_path)
            
            # 3. Parse Document
            parser = DocumentParser()
            parsed_elements = parser.parse_file(temp_path, doc.name)
            
            if not parsed_elements:
                raise ValueError("No elements parsed from the document.")
            
            # 4. Chunk Document
            # Use semantic chunking if configured, default to recursive chunker
            # We can read settings or pass parameter (let's use recursive by default, or read from env)
            use_semantic_chunking = os.getenv("USE_SEMANTIC_CHUNKING", "false").lower() == "true"
            chunker = DocumentChunker(use_semantic=use_semantic_chunking)
            chunks = chunker.chunk_document(parsed_elements)
            
            if not chunks:
                raise ValueError("Document was parsed but produced zero chunks.")
            
            # 5. Generate Embeddings in batches
            logger.info("Computing embeddings...")
            embeddings_service = HuggingFaceInferenceEmbeddings()
            texts_to_embed = [chunk["content"] for chunk in chunks]
            
            # Request all embeddings from HuggingFace
            embeddings = embeddings_service.embed_documents(texts_to_embed)
            
            # 6. Save Chunks to pgvector DB
            logger.info("Saving chunks to vector database...")
            
            # Delete old chunks if any (in case of re-processing)
            db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()
            
            db_chunks = []
            for i, chunk in enumerate(chunks):
                db_chunk = DocumentChunk(
                    id=uuid.uuid4(),
                    document_id=doc.id,
                    content=chunk["content"],
                    embedding=embeddings[i],
                    chunk_metadata={
                        **chunk["metadata"],
                        "chunk_index": i
                    }
                )
                db_chunks.append(db_chunk)
                
            db.add_all(db_chunks)
            
            # Update Document status to completed
            doc.status = "completed"
            doc.error_message = None
            db.commit()
            logger.info(f"Ingestion succeeded for document {doc.name} (ID: {document_id}) - {len(db_chunks)} chunks stored.")
            return True
            
        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)
                logger.info(f"Cleaned up temporary file: {temp_path}")
                
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to process document {document_id}: {e}", exc_info=True)
        
        # Save error details in DB
        doc = db.query(Document).filter(Document.id == uuid.UUID(document_id)).first()
        if doc:
            doc.status = "failed"
            doc.error_message = str(e)
            db.commit()
        return False
    finally:
        db.close()
