import logging
from typing import List, Dict, Any, TypedDict, Annotated
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool
from app.core.config import settings
from app.db.session import SessionLocal
from app.rag.retriever import MultiQueryExpansion, HybridRetriever, HuggingFaceReranker, reciprocal_rank_fusion
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

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
    
    # Format Context Chunks with inline citations
    context_str = ""
    citations_map = {}
    
    for idx, chunk in enumerate(chunks):
        meta = chunk.get("metadata", {})
        source_name = meta.get("source", "Unknown")
        page_num = meta.get("page_number", 1)
        
        # Unique citation identifier: e.g., doc_name_PageX
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
        
    system_prompt = (
        "You are an expert enterprise research assistant. Answer the user's question using only the provided context chunks.\n"
        "For each fact, statement, or table you reference, you MUST cite the source using the exact citation key provided in the chunk headers (e.g. [Filename.pdf_Page1]).\n"
        "Cite the key at the end of the sentence or paragraph where the fact is mentioned (e.g. 'The revenue increased by 15% [report.pdf_Page3].').\n"
        "If you use information from multiple chunks, include multiple citation keys (e.g. [report.pdf_Page3][slide.pdf_Page1]).\n"
        "Be extremely rigorous about citations. Never write a statement without citing its source from the context.\n"
        "If the answer cannot be found in the provided context, state: 'I cannot find the answer in the uploaded documents.' do not fabricate information."
    )
    
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
        if f"[{key}]" in response_text:
            used_citations.append(value)
            
    return {
        "messages": [AIMessage(content=response.content)],
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
