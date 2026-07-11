import logging
from typing import List, Dict, Any, TypedDict, Annotated
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool
from app.core.config import settings
from app.db.session import SessionLocal
from app.db.models import Document, DocumentChunk
from app.rag.retriever import MultiQueryExpansion, HybridRetriever, HuggingFaceReranker, reciprocal_rank_fusion
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate

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
        "7. If a document chunk contains an 'image_transcription' or an image block that visualizes the concept the user is asking about, you MUST not only textually describe it, but you MUST also output a standard markdown image syntax block: ![Image Description](ID) where ID matches the integer string of the citation index (e.g., ![Transformer Architecture Block Diagram](3)).\n"
        "8. If the answer cannot be found in the provided context, state: 'I cannot find the answer in the uploaded documents.' Do not fabricate any information."
    )

# Define State Structure
class RAGState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    queries: List[str]
    retrieved_chunks: List[Dict[str, Any]]
    reranked_chunks: List[Dict[str, Any]]
    user_id: str
    thread_id: str
    answer: str
    citations: List[Dict[str, Any]]

# Multi-query Expansion Node
def node_expand_queries(state: RAGState) -> Dict[str, Any]:
    logger.info("LangGraph Node: expand_queries")
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""
    
    mq = MultiQueryExpansion()
    queries = mq.expand_query(last_message)
    return {"queries": queries}

# Retrieval Node (Parallel Vector + FTS search & RRF)
def node_retrieve(state: RAGState) -> Dict[str, Any]:
    logger.info("LangGraph Node: retrieve")
    queries = state.get("queries", [])
    user_id = state.get("user_id", "")
    
    if not queries:
        return {"retrieved_chunks": []}
        
    db = SessionLocal()
    try:
        retriever = HybridRetriever(db)
        all_hits = []
        
        # Run retrieval for each query variation
        for q in queries:
            hits = retriever.retrieve_hybrid(q, user_id, limit=15)
            all_hits.append(hits)
            
        # Combine all retrieval results using RRF
        combined_hits = reciprocal_rank_fusion(all_hits, limit=20)
        return {"retrieved_chunks": combined_hits}
    finally:
        db.close()

# Reranking Node
def node_rerank(state: RAGState) -> Dict[str, Any]:
    logger.info("LangGraph Node: rerank")
    messages = state["messages"]
    last_query = messages[-1].content if messages else ""
    candidates = state.get("retrieved_chunks", [])
    
    reranker = HuggingFaceReranker()
    top_chunks = reranker.rerank(last_query, candidates, top_k=5)
    return {"reranked_chunks": top_chunks}

# Response Generation Node
def node_generate(state: RAGState) -> Dict[str, Any]:
    logger.info("LangGraph Node: generate")
    messages = state["messages"]
    chunks = state.get("reranked_chunks", [])
    # Automatically fetch and append any image chunks from the referenced documents to guarantee the LLM can reference visual assets.
    db_session = SessionLocal()
    try:
        top_chunk_ids = [c["id"] for c in chunks]
        if top_chunk_ids:
            db_chunks = db_session.query(DocumentChunk).filter(DocumentChunk.id.in_(top_chunk_ids)).all()
            doc_ids = list(set(c.document_id for c in db_chunks if c.document_id))
            if doc_ids:
                db_images = db_session.query(DocumentChunk).filter(
                    DocumentChunk.document_id.in_(doc_ids)
                ).all()
                for img_c in db_images:
                    meta = img_c.chunk_metadata or {}
                    if meta.get("is_image", False) or meta.get("type") == "image":
                        # Avoid duplicating if it was somehow already retrieved
                        if not any(c["id"] == str(img_c.id) for c in chunks):
                            chunks.append({
                                "id": str(img_c.id),
                                "content": img_c.content,
                                "metadata": meta,
                                "score": 1.0
                            })
    except Exception as append_err:
        logger.warning(f"Failed to automatically pull related image chunks in graph node: {append_err}")
    finally:
        db_session.close()
    
    # Format Context Chunks with metadata keys
    context_str = ""
    citations_map = {}
    
    for idx, chunk in enumerate(chunks):
        meta = chunk.get("metadata", {})
        source_name = meta.get("source", "Unknown")
        page_num = meta.get("page_number", 1)
        storage_path = meta.get("storage_path", source_name)
        cite_key = f"[^{idx+1}]"
        
        # Dynamic content_type detection
        if "text_as_html" in meta:
            content_type = "table"
        elif meta.get("file_type", "").startswith("image/") or "image" in meta.get("file_type", "").lower() or meta.get("is_image", False):
            content_type = "image_transcription"
        else:
            content_type = "text"
            
        # Dynamic presigned download link generation for Cloudflare R2 if credentials are set
        download_url = None
        if meta.get("is_image", False) and meta.get("image_base64"):
            download_url = f"data:image/png;base64,{meta['image_base64']}"
        else:
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
            display_url = download_url
            if display_url.startswith("data:image/"):
                display_url = "data:image/png;base64,[BASE64_IMAGE_DATA_TRUNCATED]"
            context_str += f"Source Link: {display_url}\n"
        context_str += f"Content: {chunk['content']}\n"
        if "text_as_html" in meta:
            context_str += f"[Table HTML: {meta['text_as_html']}]\n"
        context_str += f"--- END CHUNK ---\n\n"
        
    system_prompt = LocalAgentConfig.SYSTEM_INSTRUCTIONS
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("system", "Context chunks:\n\n{context}"),
        # Pass conversation history except the last message, then add last message
        *messages[:-1],
        ("human", "{question}")
    ])
    
    llm = ChatGroq(
        groq_api_key=settings.GROQ_API_KEY,
        model_name="llama-3.3-70b-versatile",  # Stronger model for generation/citations
        temperature=0.0
    )
    
    chain = prompt | llm
    
    question = messages[-1].content if messages else ""
    response = chain.invoke({
        "context": context_str,
        "question": question
    })
    
    # Extract citations used in the response
    used_citations = []
    response_text = response.content
    
    for key, value in citations_map.items():
        idx = value.get("index")
        if (key in response_text) or (idx is not None and (f"({idx})" in response_text or f"[{idx}]" in response_text)):
            used_citations.append(value)
            
    return {
        "messages": [AIMessage(content=response.content, additional_kwargs={"citations": used_citations})],
        "answer": response.content,
        "citations": used_citations
    }

# Build and Compile Workflow Graph
def get_rag_graph():
    # Setup StateGraph
    workflow = StateGraph(RAGState)
    
    # Define Nodes
    workflow.add_node("expand_queries", node_expand_queries)
    workflow.add_node("retrieve", node_retrieve)
    workflow.add_node("rerank", node_rerank)
    workflow.add_node("generate", node_generate)
    
    # Define Edges
    workflow.add_edge(START, "expand_queries")
    workflow.add_edge("expand_queries", "retrieve")
    workflow.add_edge("retrieve", "rerank")
    workflow.add_edge("rerank", "generate")
    workflow.add_edge("generate", END)
    
    # Checkpointer Setup for Persistence
    connection_string = settings.DATABASE_URL
    
    # PostgresSaver uses standard connection pool from psycopg_pool
    # Let's handle cases where database is not configured (e.g. unit tests or local dev checkouts)
    try:
        pool = ConnectionPool(conninfo=connection_string, min_size=1, max_size=5)
        checkpointer = PostgresSaver(pool)
        # Ensure saver tables exist
        checkpointer.setup()
        graph = workflow.compile(checkpointer=checkpointer)
        logger.info("Compiled LangGraph with Postgres checkpointer successfully.")
    except Exception as e:
        logger.error(f"Failed to setup Postgres checkpointer: {e}. Compiling graph without memory persistence.")
        graph = workflow.compile()
        
    return graph
