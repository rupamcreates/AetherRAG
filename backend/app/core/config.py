import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # App Settings
    ENV: str = "development"
    DEBUG: bool = True
    PROJECT_NAME: str = "Enterprise Multimodal RAG API"

    # API Server
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/rag_db"

    # Redis Task Queue
    REDIS_URL: str = "redis://localhost:6379/0"

    # Storage Settings
    STORAGE_PROVIDER: str = "local"  # 'local', 'supabase', or 's3'
    STORAGE_BUCKET_NAME: str = "documents"
    LOCAL_STORAGE_DIR: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "storage")

    # Supabase Settings
    SUPABASE_URL: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None

    # S3 Settings
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: Optional[str] = "us-east-1"
    S3_ENDPOINT_URL: Optional[str] = None

    # LLM and Embeddings API Keys
    GROQ_API_KEY: Optional[str] = None
    HUGGINGFACE_API_KEY: Optional[str] = None

    # Embedding Configurations
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIMENSION: int = 384

    # Unstructured.io Configurations
    UNSTRUCTURED_API_KEY: Optional[str] = None
    UNSTRUCTURED_API_URL: str = "https://api.unstructuredapp.io/general/v0/general"

    # Clerk Security
    CLERK_SECRET_KEY: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
