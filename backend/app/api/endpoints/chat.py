import uuid
import json
import logging
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.api.deps import get_db, get_current_user
from app.db.models import ChatThread, Document
from app.rag.graph import get_rag_graph
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from app.core.config import settings
from app.rag.retriever import MultiQueryExpansion, HybridRetriever, HuggingFaceReranker, reciprocal_rank_fusion
from pydantic import BaseModel
from datetime import datetime

import re
from typing import Optional

logger = logging.getLogger(__name__)

class LocalAgentConfig:
    SYSTEM_INSTRUCTIONS = (
        "You are an expert enterprise research assistant. Answer the user's question using ONLY the provided context chunks.\n\n"
        "Strict rules for citations, formatting, and explanations:\n"
        "1. Synthesize your answer solely using the bounded context chunks. Do not include raw filename strings, file paths, or raw text suffixes in the body of your response text (e.g. do NOT write 'Paper.pdf' or 'report.txt' directly in the text unless referencing it inside the bracket citation).\n"
        "2. Explain everything nicely and step-by-step to the user while answering their questions.\n"
        "3. Enforce clean alphanumeric markdown citation tokens (e.g., [^1], [^2]) right after factual assertions or references to a chunk.\n"
        "4. If duplicate or clustered citations appear for a statement, group them into a single, clean token (e.g., [^1, 2] instead of [^1][^2] or [^1] [^2]).\n"
        "5. If a chunk contains a 'table' or 'image_transcription', you MUST explicitly acknowledge and reference it visually (e.g., 'As illustrated in the diagram [^3]...' or 'According to the data table [^1]...').\n"
        "6. If you reference data from a table chunk, reconstruct it as a clean Markdown table in your response.\n"
        "7. If a document chunk contains an 'image_transcription' or an image block that visualizes the concept the user is asking about, you MUST not only textually describe it, but you MUST also output a standard markdown image syntax block: `![Image Description](ID)` where ID matches the integer string of the citation index (e.g., `![Transformer Architecture Block Diagram](3)`).\n"
        "8. If the answer cannot be found in the provided context, state: 'I cannot find the answer in the uploaded documents.' Do not fabricate any information."
    )

class CitationStreamProcessor:
    def __init__(self):
        self.buffer = ""
        self.yielded_content = ""

    def process(self, token: str) -> str:
        self.buffer += token
        
        # Withhold yielding if the buffer ends in the middle of a citation tag (e.g. '[', '[^', '[^1', '[^1,')
        if re.search(r'\[\^?[\d,\s]*$', self.buffer):
            return ""
            
        to_yield = self.buffer
        self.buffer = ""
        
        # Clean inline duplicate citation tokens (e.g., [^1][^1] -> [^1])
        to_yield = re.sub(r'(\[\^[\d,\s]+\])\s*\1', r'\1', to_yield)
        
        self.yielded_content += to_yield
        return to_yield

    def flush(self) -> str:
        remaining = self.buffer
        self.buffer = ""
        
        # Clean duplicate citations in the remaining buffer
        remaining = re.sub(r'(\[\^[\d,\s]+\])\s*\1', r'\1', remaining)
        
        full_text = self.yielded_content + remaining
        
        # Strip trailing duplicate citation suffixes globally from the end of the response
        cleaned = re.sub(r'(\[\^[\d,\s]+\])(?:\s*\1)+$', r'\1', full_text)
        
        # Return only the newly cleaned content that hasn't been yielded yet
        new_yield = cleaned[len(self.yielded_content):]
        return new_yield

router = APIRouter()

class ThreadCreate(BaseModel):
    title: str = "New Chat"

class ThreadOut(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class QueryIn(BaseModel):
    thread_id: uuid.UUID
    message: str

class CitationOut(BaseModel):
    source: str
    page_number: int
    content_preview: str
    download_url: Optional[str] = None
    index: Optional[int] = None

class QueryOut(BaseModel):
    answer: str
    citations: List[CitationOut]

class MessageHistoryOut(BaseModel):
    role: str
    content: str
    citations: Optional[List[CitationOut]] = None

@router.post("/threads", response_model=ThreadOut, status_code=status.HTTP_201_CREATED)
def create_thread(
    thread_in: ThreadCreate,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user)
):
    thread = ChatThread(
        id=uuid.uuid4(),
        user_id=user_id,
        title=thread_in.title
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread

@router.get("/threads", response_model=List[ThreadOut])
def list_threads(
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user)
):
    threads = db.query(ChatThread).filter(ChatThread.user_id == user_id).order_by(ChatThread.updated_at.desc()).all()
    return threads

@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_thread(
    thread_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user)
):
    thread = db.query(ChatThread).filter(ChatThread.id == thread_id, ChatThread.user_id == user_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Chat thread not found.")
        
    try:
        # Delete chat thread metadata
        db.delete(thread)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete thread: {e}"
        )
        
    try:
        # Clean up LangGraph checkpointer tables for this thread to prevent db bloat
        # Tables created by PostgresSaver: checkpoints, checkpoint_writes, checkpoint_blobs
        # Columns include thread_id
        db.execute(text("DELETE FROM checkpoints WHERE thread_id = :thread_id"), {"thread_id": str(thread_id)})
        db.execute(text("DELETE FROM checkpoint_writes WHERE thread_id = :thread_id"), {"thread_id": str(thread_id)})
        db.execute(text("DELETE FROM checkpoint_blobs WHERE thread_id = :thread_id"), {"thread_id": str(thread_id)})
        db.commit()
    except Exception as se:
        db.rollback()
        logger.warning(f"Failed to clean up checkpoints tables: {se} (expected if checkpointer tables are not created)")

@router.post("/query")
async def query_rag(
    query_in: QueryIn,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user)
):
    # Verify thread ownership
    thread = db.query(ChatThread).filter(ChatThread.id == query_in.thread_id, ChatThread.user_id == user_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Chat thread not found or access denied.")
        
    async def event_generator():
        try:
            # 1. Run Query Expansion
            mq = MultiQueryExpansion()
            queries = mq.expand_query(query_in.message)
            
            # 2. Run Hybrid Retrieval (Vector + Full-Text Search)
            retriever = HybridRetriever(db)
            all_hits = []
            for q in queries:
                hits = retriever.retrieve_hybrid(q, user_id, limit=15)
                all_hits.append(hits)
                
            combined_hits = reciprocal_rank_fusion(all_hits, limit=20)
            
            # 3. Run Reranking
            reranker = HuggingFaceReranker()
            top_chunks = reranker.rerank(query_in.message, combined_hits, top_k=5)
            
            # 4. Format Context Chunks with metadata keys
            context_str = ""
            citations_map = {}
            for idx, chunk in enumerate(top_chunks):
                meta = chunk.get("metadata", {})
                source_name = meta.get("source", "Unknown")
                page_num = meta.get("page_number", 1)
                storage_path = meta.get("storage_path", source_name)
                if meta.get("is_image", False) and meta.get("image_path"):
                    storage_path = meta.get("image_path")
                    
                cite_key = f"[^{idx+1}]"
                
                # Dynamic content_type detection
                if "text_as_html" in meta:
                    content_type = "table"
                elif meta.get("file_type", "").startswith("image/") or "image" in meta.get("file_type", "").lower() or meta.get("is_image", False):
                    content_type = "image_transcription"
                else:
                    content_type = "text"
                
                # Dynamic presigned download link generation for Cloudflare R2
                download_url = None
                provider = settings.STORAGE_PROVIDER.lower()
                if provider in ("r2", "s3") and settings.CLOUDFLARE_ACCOUNT_ID and settings.R2_ACCESS_KEY_ID:
                    try:
                        import boto3
                        from botocore.config import Config
                        
                        endpoint_url = f"https://{settings.CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"
                        s3_client = boto3.client(
                            "s3",
                            endpoint_url=endpoint_url,
                            aws_access_key_id=settings.R2_ACCESS_KEY_ID or settings.AWS_ACCESS_KEY_ID,
                            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY or settings.AWS_SECRET_ACCESS_KEY,
                            config=Config(signature_version="s3v4"),
                            region_name="us-east-1"
                        )
                        bucket = settings.R2_BUCKET_NAME or settings.STORAGE_BUCKET_NAME
                        download_url = s3_client.generate_presigned_url(
                            ClientMethod="get_object",
                            Params={
                                "Bucket": bucket,
                                "Key": storage_path
                            },
                            ExpiresIn=3600
                        )
                    except Exception as s3_err:
                        logger.warning(f"Failed to generate R2 download URL for citation: {s3_err}")
                
                if not download_url:
                    if storage_path:
                        download_url = f"{settings.BACKEND_URL}/api/documents/file?path={storage_path}"
                
                citations_map[cite_key] = {
                    "source": source_name,
                    "page_number": page_num,
                    "content_preview": chunk["content"][:200] + "...",
                    "download_url": download_url,
                    "index": idx + 1
                }
                context_str += f"--- START CHUNK {cite_key} ---\n"
                context_str += f"Source: {source_name} (Page {page_num})\n"
                context_str += f"Content Type: {content_type}\n"
                if download_url:
                    context_str += f"Source Link: {download_url}\n"
                context_str += f"Content: {chunk['content']}\n"
                if "text_as_html" in meta:
                    context_str += f"[Table HTML: {meta['text_as_html']}]\n"
                context_str += f"--- END CHUNK ---\n\n"
                
            # 5. Build Chat Prompt and load Thread History
            system_prompt = LocalAgentConfig.SYSTEM_INSTRUCTIONS
            
            # Load memory history from LangGraph checkpointer
            graph = get_rag_graph()
            config = {"configurable": {"thread_id": str(query_in.thread_id)}}
            try:
                state_snapshot = graph.get_state(config)
                history = state_snapshot.values.get("messages", []) if state_snapshot.values else []
            except Exception as se:
                logger.warning(f"Failed to fetch state from checkpointer: {se}")
                history = []
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("system", "Context chunks:\n\n{context}"),
                *history,
                ("human", "{question}")
            ])
            
            llm = ChatGroq(
                groq_api_key=settings.GROQ_API_KEY,
                model_name="llama-3.3-70b-versatile",
                temperature=0.0
            )
            
            chain = prompt | llm
            
            # 6. Stream tokens to the client in real-time with duplicate citation filter
            accumulated_answer = ""
            processor = CitationStreamProcessor()
            async for chunk in chain.astream({
                "context": context_str,
                "question": query_in.message
            }):
                token = chunk.content
                processed_token = processor.process(token)
                if processed_token:
                    accumulated_answer += processed_token
                    yield f"data: {json.dumps({'token': processed_token})}\n\n"
            
            # Flush remaining buffer content
            final_token = processor.flush()
            if final_token:
                accumulated_answer += final_token
                yield f"data: {json.dumps({'token': final_token})}\n\n"
                
            # 7. Extract citations actually used in the response
            used_citations = []
            for key, value in citations_map.items():
                if key in accumulated_answer:
                    used_citations.append(value)
                    
            # 8. Save updated chat history in memory checkpointer
            try:
                new_messages = history + [
                    HumanMessage(content=query_in.message),
                    AIMessage(content=accumulated_answer, additional_kwargs={"citations": used_citations})
                ]
                graph.update_state(config, {"messages": new_messages})
            except Exception as se:
                logger.warning(f"Skipping checkpointer state update (saver tables may not exist): {se}")
            
            # Update thread updated_at timestamp
            thread.updated_at = datetime.utcnow()
            db.commit()
            
            # 9. Yield the final citations packet
            yield f"data: {json.dumps({'citations': used_citations})}\n\n"
            
        except Exception as e:
            logger.error(f"Error in query streaming: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.get("/threads/{thread_id}/history", response_model=List[MessageHistoryOut])
def get_thread_history(
    thread_id: uuid.UUID,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user)
):
    # Verify thread ownership
    thread = db.query(ChatThread).filter(ChatThread.id == thread_id, ChatThread.user_id == user_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Chat thread not found or access denied.")
        
    try:
        # Retrieve state from LangGraph checkpointer
        graph = get_rag_graph()
        config = {"configurable": {"thread_id": str(thread_id)}}
        try:
            state_snapshot = graph.get_state(config)
            messages = state_snapshot.values.get("messages", []) if state_snapshot.values else []
        except Exception as se:
            logger.warning(f"Failed to fetch state from checkpointer: {se}")
            messages = []
        
        formatted_history = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                formatted_history.append(MessageHistoryOut(role="user", content=msg.content))
            elif isinstance(msg, AIMessage):
                cites = msg.additional_kwargs.get("citations")
                formatted_history.append(MessageHistoryOut(role="assistant", content=msg.content, citations=cites))
                
        return formatted_history
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch conversation history: {e}"
        )
