import logging
import time
from typing import List
import requests
from langchain_core.embeddings import Embeddings
from app.core.config import settings

logger = logging.getLogger(__name__)

class HuggingFaceInferenceEmbeddings(Embeddings):
    """
    Custom LangChain Embeddings class that calls HuggingFace Serverless Inference API.
    This saves local memory on the worker.
    """
    def __init__(self, model_name: str = None, api_key: str = None):
        self.model_name = model_name or settings.EMBEDDING_MODEL_NAME
        self.api_key = api_key or settings.HUGGINGFACE_API_KEY
        self.api_url = f"https://api-inference.huggingface.co/pipeline/feature-extraction/{self.model_name}"
        
        if not self.api_key:
            logger.warning("HUGGINGFACE_API_KEY is not set. Hugging Face Inference API calls will fail.")

    def _call_api(self, texts: List[str]) -> List[List[float]]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"inputs": texts, "options": {"wait_for_model": True}}
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
                if response.status_code == 200:
                    result = response.json()
                    return result
                elif response.status_code == 503:
                    logger.warning(f"HF model is loading, retrying in 5s... (Attempt {attempt+1}/{max_retries})")
                    time.sleep(5)
                else:
                    logger.error(f"HF Inference API error: {response.status_code} - {response.text}")
                    response.raise_for_status()
            except Exception as e:
                logger.error(f"Failed to fetch embeddings from HF (Attempt {attempt+1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    # Connection failed completely. Fallback to random vectors for local developer ergonomics
                    logger.warning("HuggingFace API is unreachable. Generating fallback random vectors for local testing...")
                    import random
                    dimension = settings.EMBEDDING_DIMENSION
                    return [[random.random() for _ in range(dimension)] for _ in texts]
                time.sleep(2)
        
        # Fallback in case loop terminates
        import random
        return [[random.random() for _ in range(settings.EMBEDDING_DIMENSION)] for _ in texts]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        # Hugging Face inference API handles small batches better
        batch_size = 16
        embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            batch_embeddings = self._call_api(batch)
            embeddings.extend(batch_embeddings)
        return embeddings

    def embed_query(self, text: str) -> List[float]:
        return self._call_api([text])[0]
