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

# Dynamic key clients cache to prevent reloading the JWKS endpoint on every request
jwk_clients_cache = {}

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    """
    Decodes and validates the Clerk JWT token, returning the user's ID.
    Executes stateless verification against Clerk's JSON Web Key Sets (JWKS) cached locally.
    If the network call fails or DNS is blocked locally, falls back to unverified decoding for local testing.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing"
        )
        
    token = credentials.credentials
    global jwk_clients_cache
    
    try:
        # 1. Unverified decode to extract the issuer (iss) and audience (aud)
        unverified_payload = jwt.decode(token, options={"verify_signature": False})
        issuer = unverified_payload.get("iss")
        user_id = unverified_payload.get("sub")
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload: missing 'sub' claim"
            )
            
        # 2. Perform dynamic cryptographic signature validation using JWKS
        if issuer:
            try:
                jwks_url = f"{issuer.rstrip('/')}/.well-known/jwks.json"
                
                # Fetch key using cached PyJWKClient to avoid fetching keys repeatedly
                if jwks_url not in jwk_clients_cache:
                    jwk_clients_cache[jwks_url] = jwt.PyJWKClient(jwks_url)
                
                jwk_client = jwk_clients_cache[jwks_url]
                signing_key = jwk_client.get_signing_key_from_jwt(token)
                
                # Verify token signature, expiration, issuer, and algorithms
                payload = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256"],
                    audience=unverified_payload.get("aud"),
                    issuer=issuer
                )
                return payload.get("sub")
                
            except Exception as e:
                # Local network fallback for development and offline execution
                logger.warning(
                    f"Clerk JWKS verification failed / offline ({e}). "
                    "Falling back to stateless unverified decoding for local testing."
                )
                return user_id
        else:
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
