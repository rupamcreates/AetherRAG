# Globally disable IPv6 to force requests and sockets to resolve hostnames via IPv4 only.
# This prevents NameResolutionError for HuggingFace on Render.com free containers.
try:
    import urllib3.util.connection as urllib3_connection
    urllib3_connection.HAS_IPV6 = False
except Exception:
    pass

try:
    import requests.packages.urllib3.util.connection as urllib3_connection
    urllib3_connection.HAS_IPV6 = False
except Exception:
    pass

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.init_db import init_db
from app.api.router import api_router

# Configure logger
logging.basicConfig(
    level=logging.INFO if settings.DEBUG else logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables and extensions on start
    logger.info("Initializing database components...")
    try:
        init_db()
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}")
        
    yield
    # Cleanup on shutdown
    logger.info("Shutting down API services...")

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Scalable Multimodal RAG API built with FastAPI, LangChain, and LangGraph",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware configuration (Frontend on Vercel)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production frontend domain in deployment phase
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include core API routes
app.include_router(api_router, prefix="/api")

@app.get("/health", tags=["system"])
def health_check():
    return {
        "status": "healthy",
        "environment": settings.ENV,
        "database_url_configured": bool(settings.DATABASE_URL),
        "redis_url_configured": bool(settings.REDIS_URL),
        "groq_api_configured": bool(settings.GROQ_API_KEY),
        "huggingface_api_configured": bool(settings.HUGGINGFACE_API_KEY)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
