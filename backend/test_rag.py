import os
import uuid
import sys
from sqlalchemy import text

# Add current directory to path to allow importing app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.config import settings
from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.db.models import Document, DocumentChunk, ChatThread
from app.rag.embeddings import HuggingFaceInferenceEmbeddings
from app.rag.graph import get_rag_graph
from langchain_core.messages import HumanMessage

def test_pipeline():
    print("--- starting pipeline integration test ---")
    
    # 1. Initialize Database
    print("\n1. Initializing database tables and extensions...")
    init_db()
    
    db = SessionLocal()
    try:
        # Create a mock user ID
        user_id = "test_user_999"
        
        # 2. Check if we can create a mock Document
        print("\n2. Creating mock document record...")
        doc = Document(
            id=uuid.uuid4(),
            name="financial_report.pdf",
            file_type="application/pdf",
            storage_path="mock/financial_report.pdf",
            user_id=user_id,
            status="completed" # Pre-set to completed for query test
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        print(f"Mock document created with ID: {doc.id}")
        
        # 3. Create mock chunks and generate vectors
        print("\n3. Inserting mock document chunks with embeddings...")
        
        # Mock paragraph text
        chunks_data = [
            "Tesla Q3 2023 revenue reached $23.35 billion, representing a 9% increase year-over-year [Source: financial_report.pdf_Page1]. Operating income was $1.76 billion.",
            "SpaceX successfully completed its 50th Falcon 9 launch of the year on Friday [Source: financial_report.pdf_Page2]. The payload was successfully deployed into orbit.",
            "Apple AAPL net sales were $89.5 billion for the fiscal fourth quarter ended September 30, 2023 [Source: financial_report.pdf_Page3]. Gross margin was 45.2%."
        ]
        
        # We need embeddings. If HUGGINGFACE_API_KEY is not set, we can check or mock it.
        # Let's try to call the HuggingFace embeddings API. If it fails, we fall back to random float vectors.
        embeddings_service = HuggingFaceInferenceEmbeddings()
        
        try:
            print("Fetching embeddings from HuggingFace Serverless API...")
            embeddings = embeddings_service.embed_documents(chunks_data)
        except Exception as e:
            print(f"HuggingFace API failed or not configured: {e}. Falling back to mock random vectors.")
            import random
            embeddings = [[random.random() for _ in range(settings.EMBEDDING_DIMENSION)] for _ in chunks_data]
            
        # Store chunks
        db_chunks = []
        for i, text_content in enumerate(chunks_data):
            db_chunk = DocumentChunk(
                id=uuid.uuid4(),
                document_id=doc.id,
                content=text_content,
                embedding=embeddings[i],
                metadata={
                    "source": doc.name,
                    "page_number": i + 1,
                    "file_type": doc.file_type,
                    "chunk_index": i
                }
            )
            db_chunks.append(db_chunk)
            
        db.add_all(db_chunks)
        db.commit()
        print(f"Successfully inserted {len(db_chunks)} chunks with size {settings.EMBEDDING_DIMENSION} vectors.")
        
        # 4. Create chat thread
        print("\n4. Creating chat thread...")
        thread = ChatThread(
            id=uuid.uuid4(),
            user_id=user_id,
            title="Tesla Revenue Test"
        )
        db.add(thread)
        db.commit()
        db.refresh(thread)
        print(f"Thread created with ID: {thread.id}")
        
        # 5. Run LangGraph RAG query
        print("\n5. Invoking LangGraph RAG workflow query...")
        # Querying something about Tesla
        query = "What was Tesla's Q3 2023 revenue?"
        
        # Let's compile graph
        graph = get_rag_graph()
        config = {"configurable": {"thread_id": str(thread.id)}}
        
        # We need GROQ_API_KEY for LLM generation.
        # If it's missing, catch the error.
        if not settings.GROQ_API_KEY:
            print("WARNING: GROQ_API_KEY is missing. LLM generation node will fail.")
            print("Skipping LLM execution step...")
        else:
            state = graph.invoke({
                "messages": [HumanMessage(content=query)],
                "user_id": user_id,
                "thread_id": str(thread.id)
            }, config=config)
            
            print("\n=== RAG PIPELINE RESPONSE ===")
            print(f"Question: {query}")
            print(f"Answer: {state.get('answer')}")
            print("Citations:")
            for cite in state.get("citations", []):
                print(f" - {cite['source']} (Page {cite['page_number']})")
            print("=============================")
            
        # Clean up database test objects
        print("\n6. Cleaning up database integration test records...")
        try:
            db.delete(thread)
            db.delete(doc)
            db.commit()
        except Exception as e:
            print(f"Error during ORM deletes: {e}")
            db.rollback()

        try:
            db.execute(text("DELETE FROM checkpoints WHERE thread_id = :thread_id"), {"thread_id": str(thread.id)})
            db.execute(text("DELETE FROM checkpoint_writes WHERE thread_id = :thread_id"), {"thread_id": str(thread.id)})
            db.execute(text("DELETE FROM checkpoint_blobs WHERE thread_id = :thread_id"), {"thread_id": str(thread.id)})
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Skipping checkpoints table cleanup: {e}")
        print("Cleanup completed successfully.")
        
    except Exception as e:
        db.rollback()
        print(f"\nERROR: Integration test pipeline failed: {e}")
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    test_pipeline()
