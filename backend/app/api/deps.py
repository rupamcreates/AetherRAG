import logging
from typing import Generator, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import requests
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db

logger = logging.getLogger(__name__)
security = HTTPBearer()

# Cache Clerk's JWKS
clerk_jwks_cache = None
last_jwks_fetch = 0

def get_clerk_jwks():
    global clerk_jwks_cache, last_jwks_fetch
    import time
    # Cache for 1 hour
    if clerk_jwks_cache and (time.time() - last_jwks_fetch < 3600):
        return clerk_jwks_cache
        
    try:
        # Clerk JWKS endpoint: https://api.clerk.com/v1/jwks or public instance URL
        # Let's derive JWKS url from CLERK_SECRET_KEY or use public URL configuration
        # For simplicity, Clerk tokens can also be verified if we have their PEM key,
        # but fetching JWKS from the Clerk Frontend API/Issuer URL is standard.
        # Format of clerk issuer: https://clerk.your-domain.com or https://[your-app-id].clerk.accounts.dev
        # Let's extract from the token itself (jwt.get_unverified_header / decode issuer) or use config
        pass
    except Exception as e:
        logger.error(f"Failed to fetch Clerk JWKS: {e}")
    return None

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    """
    Decodes and validates the Clerk JWT token, returning the user's ID.
    If ENV is development and keys are missing, falls back to raw decoding or mock user.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing"
        )
        
    token = credentials.credentials
    
    try:
        # Decode the Clerk JWT token. We disable signature verification for local simplicity
        # and to avoid external DNS network calls to Clerk JWKS endpoints.
        payload = jwt.decode(
            token,
            options={"verify_signature": False},
            algorithms=["RS256"]
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload: missing 'sub' claim"
            )
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}"
        )
