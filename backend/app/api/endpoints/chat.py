import uuid
import json
import logging
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.api.deps import get_db, get_current_user
from app.db.models import ChatThread
from app.rag.graph import get_rag_graph
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from app.core.config import settings
from app.rag.retriever import MultiQueryExpansion, HybridRetriever, HuggingFaceReranker, reciprocal_rank_fusion
from pydantic import BaseModel
from datetime import datetime

logger = logging.getLogger(__name__)

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

class QueryOut(BaseModel):
    answer: str
    citations: List[CitationOut]

class MessageHistoryOut(BaseModel):
    role: str
    content: str

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
                cite_key = f"{source_name}_Page{page_num}"
                citations_map[cite_key] = {
                    "source": source_name,
                    "page_number": page_num,
                    "content_preview": chunk["content"][:200] + "..."
                }
                context_str += f"--- START CHUNK {idx+1} [Citation Key: {cite_key}] ---\n"
                context_str += f"{chunk['content']}\n"
                if "text_as_html" in meta:
                    context_str += f"[Table HTML: {meta['text_as_html']}]\n"
                context_str += f"--- END CHUNK {idx+1} ---\n\n"
                
            # 5. Build Chat Prompt and load Thread History
            system_prompt = (
                "You are an expert enterprise research assistant. Answer the user's question using only the provided context chunks.\n"
                "For each fact, statement, or table you reference, you MUST cite the source using the exact citation key provided in the chunk headers (e.g. [Filename.pdf_Page1]).\n"
                "Cite the key at the end of the sentence or paragraph where the fact is mentioned (e.g. 'The revenue increased by 15% [report.pdf_Page3].').\n"
                "If you use information from multiple chunks, include multiple citation keys (e.g. [report.pdf_Page3][slide.pdf_Page1]).\n"
                "Be extremely rigorous about citations. Never write a statement without citing its source from the context.\n"
                "If the answer cannot be found in the provided context, state: 'I cannot find the answer in the uploaded documents.' do not fabricate information."
            )
            
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
            
            # 6. Stream tokens to the client in real-time
            accumulated_answer = ""
            async for chunk in chain.astream({
                "context": context_str,
                "question": query_in.message
            }):
                token = chunk.content
                accumulated_answer += token
                yield f"data: {json.dumps({'token': token})}\n\n"
                
            # 7. Extract citations actually used in the response
            used_citations = []
            for key, value in citations_map.items():
                if f"[{key}]" in accumulated_answer:
                    used_citations.append(value)
                    
            # 8. Save updated chat history in memory checkpointer
            try:
                new_messages = history + [
                    HumanMessage(content=query_in.message),
                    AIMessage(content=accumulated_answer)
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
                formatted_history.append(MessageHistoryOut(role="assistant", content=msg.content))
                
        return formatted_history
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch conversation history: {e}"
        )
