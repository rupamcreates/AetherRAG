import logging
from typing import List, Dict, Any, Tuple
from sqlalchemy import text
from sqlalchemy.orm import Session
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from app.core.config import settings
from app.rag.embeddings import HuggingFaceInferenceEmbeddings
import requests
import time

logger = logging.getLogger(__name__)

class MultiQueryExpansion:
    def __init__(self):
        self.llm = ChatGroq(
            groq_api_key=settings.GROQ_API_KEY,
            model_name="llama-3.1-8b-instant",  # Fast and light model for query expansion
            temperature=0.2
        )
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an AI language model assistant. Your task is to generate 3 alternative versions of the user's query to retrieve relevant documents from a vector database.\n"
                       "By generating multiple perspectives on the user query, your goal is to help the user overcome some of the limitations of distance-based similarity search.\n"
                       "Provide these alternative queries separated by newlines, without numbers or introductory text. Just output the queries, one per line."),
            ("human", "{query}")
        ])
        self.chain = self.prompt | self.llm

    def expand_query(self, query: str) -> List[str]:
        try:
            response = self.chain.invoke({"query": query})
            expanded = [q.strip() for q in response.content.split("\n") if q.strip()]
            # Keep only the first 3 queries, and prepend the original query
            queries = [query] + expanded[:3]
            logger.info(f"Expanded queries: {queries}")
            return queries
        except Exception as e:
            logger.error(f"Failed to expand query: {e}")
            return [query]  # Fallback to original query on failure

class HybridRetriever:
    def __init__(self, db: Session):
        self.db = db
        self.embeddings = HuggingFaceInferenceEmbeddings()

    def vector_search(self, query: str, user_id: str, limit: int = 15) -> List[Dict[str, Any]]:
        """Performs vector search in PostgreSQL using pgvector."""
        try:
            query_vector = self.embeddings.embed_query(query)
            # Use raw SQL for pgvector compatibility and efficiency
            sql = text("""
                SELECT dc.id, dc.content, dc.chunk_metadata, (dc.embedding <=> :embedding) AS distance 
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE d.user_id = :user_id AND d.status = 'completed'
                ORDER BY distance ASC
                LIMIT :limit
            """)
            
            result = self.db.execute(sql, {
                "embedding": str(query_vector),
                "user_id": user_id,
                "limit": limit
            })
            
            hits = []
            for row in result:
                hits.append({
                    "id": str(row[0]),
                    "content": row[1],
                    "metadata": row[2],
                    "score": 1 - row[3]  # Convert distance (0 to 2) to similarity score
                })
            return hits
        except Exception as e:
            logger.error(f"Vector search failed: {e}", exc_info=True)
            return []

    def keyword_search(self, query: str, user_id: str, limit: int = 15) -> List[Dict[str, Any]]:
        """Performs PostgreSQL Full-Text Search as lexical search."""
        try:
            sql = text("""
                SELECT dc.id, dc.content, dc.chunk_metadata, ts_rank_cd(to_tsvector('english', dc.content), plainto_tsquery('english', :query)) AS rank
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE d.user_id = :user_id AND d.status = 'completed'
                  AND to_tsvector('english', dc.content) @@ plainto_tsquery('english', :query)
                ORDER BY rank DESC
                LIMIT :limit
            """)
            
            result = self.db.execute(sql, {
                "query": query,
                "user_id": user_id,
                "limit": limit
            })
            
            hits = []
            for row in result:
                hits.append({
                    "id": str(row[0]),
                    "content": row[1],
                    "metadata": row[2],
                    "score": row[3]
                })
            return hits
        except Exception as e:
            logger.error(f"Keyword search failed: {e}", exc_info=True)
            return []

    def retrieve_hybrid(self, query: str, user_id: str, limit: int = 15) -> List[Dict[str, Any]]:
        """Retrieves and merges vector and keyword search candidates using Reciprocal Rank Fusion (RRF)."""
        vector_results = self.vector_search(query, user_id, limit=limit)
        keyword_results = self.keyword_search(query, user_id, limit=limit)
        
        # Merge using Reciprocal Rank Fusion
        return reciprocal_rank_fusion([vector_results, keyword_results], limit=limit)

def reciprocal_rank_fusion(results_lists: List[List[Dict[str, Any]]], k: int = 60, limit: int = 15) -> List[Dict[str, Any]]:
    """
    RRF algorithm to merge and re-rank results from different retrieval runs.
    Each item in results_lists is a ranked list of hits.
    """
    rrf_scores: Dict[str, float] = {}
    item_map: Dict[str, Dict[str, Any]] = {}
    
    for results in results_lists:
        for rank, item in enumerate(results):
            item_id = item["id"]
            item_map[item_id] = item
            
            # RRF formula: 1 / (k + rank)
            score = 1.0 / (k + rank)
            rrf_scores[item_id] = rrf_scores.get(item_id, 0.0) + score
            
    # Sort by RRF score descending
    sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
    
    merged_results = []
    for item_id in sorted_ids[:limit]:
        item = item_map[item_id].copy()
        item["rrf_score"] = rrf_scores[item_id]
        merged_results.append(item)
        
    return merged_results

class HuggingFaceReranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-base"):
        self.model_name = model_name
        self.api_key = settings.HUGGINGFACE_API_KEY
        self.api_url = f"https://api-inference.huggingface.co/models/{self.model_name}"

    def rerank(self, query: str, candidates: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
        if not candidates:
            return []
            
        if not self.api_key:
            logger.warning("HUGGINGFACE_API_KEY not set. Skipping reranking.")
            return candidates[:top_k]
            
        payload = {
            "inputs": [
                {"text": query, "text_pair": doc["content"]} for doc in candidates
            ]
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
                if response.status_code == 200:
                    scores = response.json()
                    
                    # HF rerankers return scores in various formats depending on output structure.
                    # BGE-reranker usually returns a list of floats (the higher the score, the more relevant)
                    # or list of dicts with score key. Let's parse both.
                    
                    # Map scores back to candidates
                    scored_candidates = []
                    for i, cand in enumerate(candidates):
                        score = scores[i]
                        if isinstance(score, dict) and "score" in score:
                            score_val = score["score"]
                        else:
                            score_val = float(score)
                        
                        cand_copy = cand.copy()
                        cand_copy["rerank_score"] = score_val
                        scored_candidates.append(cand_copy)
                        
                    # Sort candidates by rerank score descending
                    scored_candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
                    return scored_candidates[:top_k]
                    
                elif response.status_code == 503:
                    logger.warning(f"Reranker model loading, retrying in 5s... (Attempt {attempt+1}/{max_retries})")
                    time.sleep(5)
                else:
                    logger.error(f"HF Reranker API error: {response.status_code} - {response.text}")
                    break
            except Exception as e:
                logger.error(f"Reranking error: {e}")
                time.sleep(2)
                
        # Fallback to RRF ranking order if API fails
        logger.warning("Reranking failed. Falling back to default retrieval rankings.")
        return candidates[:top_k]
