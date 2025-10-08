"""
Authentication integration with gnosis-auth service
Based on gnosis-ahp auth client pattern with HMAC token validation
"""
import os
import hmac
import hashlib
import base64
import json
import logging
import httpx
from datetime import datetime, timezone
from typing import Dict, Optional
from fastapi import HTTPException, Header, Depends

from app.config import settings

logger = logging.getLogger(__name__)


def validate_token_from_query(token: str, secret_key: str) -> Dict:
    """
    Validates a stateless bearer token from a query parameter using a provided secret key.
    Returns the entire decoded payload if valid.
    Based on gnosis-ahp HMAC token validation.
    """
    logger.debug("Starting token validation")
    
    if not secret_key:
        raise ValueError("Secret key cannot be empty for token validation.")
    
    if not token:
        raise HTTPException(status_code=401, detail="Token cannot be empty.")
    
    try:
        # Split token into payload and signature
        token_parts = token.split(".")
        if len(token_parts) != 2:
            raise HTTPException(status_code=401, detail="Invalid token format.")
        
        encoded_payload, encoded_signature = token_parts
        
        # Verify signature
        signature_generator = hmac.new(
            secret_key.encode('utf-8'), 
            encoded_payload.encode('utf-8'), 
            hashlib.sha256
        )
        expected_signature = signature_generator.digest()
        expected_encoded_signature = base64.urlsafe_b64encode(expected_signature).rstrip(b'=').decode('utf-8')
        
        if not hmac.compare_digest(encoded_signature, expected_encoded_signature):
            raise HTTPException(status_code=401, detail="Invalid token signature.")
        
        # Decode payload
        # Add padding if needed for base64 decode
        padding = 4 - (len(encoded_payload) % 4)
        if padding != 4:
            encoded_payload += '=' * padding
            
        payload_bytes = base64.urlsafe_b64decode(encoded_payload.encode('utf-8'))
        payload = json.loads(payload_bytes.decode('utf-8'))
        
        # Check expiration
        if 'exp' in payload:
            exp_time = datetime.fromisoformat(payload['exp'].replace('Z', '+00:00'))
            if datetime.now(timezone.utc) > exp_time:
                raise HTTPException(status_code=401, detail="Token has expired.")
        
        logger.debug(f"Token validated successfully for agent: {payload.get('agent_id', 'unknown')}")
        return payload
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=401, detail="Invalid token payload format.")
    except Exception as e:
        logger.error(f"Token validation failed: {e}")
        raise HTTPException(status_code=401, detail="Token validation failed.")


class AuthClient:
    """Client for gnosis-auth service integration"""
    
    def __init__(self):
        self.auth_service_url = settings.gnosis_auth_url
        
    async def validate_token(self, token: str) -> Dict:
        """
        Validate HMAC-signed JWT bearer token (same as gnosis-ahp)
        
        Args:
            token: HMAC-signed JWT Bearer token to validate
            
        Returns:
            Dict with user info: {"subject": "email", "scopes": [...]}
            
        Raises:
            HTTPException: If token is invalid or expired
        """
        try:
            # Get secret key from environment (must match gnosis-ahp token signer)
            # Prefer AHP_SECRET_KEY for cross-service consistency; fall back to SECRET_KEY.
            secret_key = os.getenv("AHP_SECRET_KEY", os.getenv("SECRET_KEY", "gnosis-ahp-secret-key-change-in-production"))
            
            # Split token into parts
            token_parts = token.split(".")
            if len(token_parts) != 2:
                raise HTTPException(status_code=401, detail="Invalid token format")
            
            encoded_payload, encoded_signature = token_parts
            
            # Verify HMAC signature
            expected_signature_generator = hmac.new(
                secret_key.encode('utf-8'), 
                encoded_payload.encode('utf-8'), 
                hashlib.sha256
            )
            expected_signature = expected_signature_generator.digest()
            
            try:
                provided_signature = base64.urlsafe_b64decode(encoded_signature + '==')
            except Exception:
                raise HTTPException(status_code=401, detail="Invalid signature encoding")
            
            if not hmac.compare_digest(expected_signature, provided_signature):
                raise HTTPException(status_code=401, detail="Invalid token signature")
            
            # Decode payload
            try:
                payload_bytes = base64.urlsafe_b64decode(encoded_payload + '==')
                payload = json.loads(payload_bytes.decode('utf-8'))
            except Exception:
                raise HTTPException(status_code=401, detail="Invalid token payload format")
            
            # Check expiration
            if 'exp' in payload:
                exp_time = datetime.fromisoformat(payload['exp'].replace('Z', '+00:00'))
                if datetime.now(timezone.utc) > exp_time:
                    raise HTTPException(status_code=401, detail="Token has expired")
            
            # Extract user info
            subject = payload.get('sub', 'unknown@gnosis-crawl.local')
            actor = payload.get('actor', '')
            
            logger.info(f"Token validated for subject: {subject}")
            
            return {
                "subject": subject,
                "actor": actor,
                "email": subject,  # Use subject as email
                "scopes": ["crawl:*"],  # Default scopes for crawl service
                "valid": True
            }
                    
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Token validation failed: {e}")
            raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    def _create_mock_user(self, token: str) -> Dict:
        """Create mock user for development"""
        return {
            "subject": "user:dev@gnosis-crawl.local",
            "scopes": ["crawl:*"],
            "email": "dev@gnosis-crawl.local",
            "mock": True
        }


# Global auth client instance
auth_client = AuthClient()


async def get_current_user(authorization: str = Header(None)) -> Dict:
    """
    FastAPI dependency to get current authenticated user
    
    Args:
        authorization: Authorization header with Bearer token
        
    Returns:
        Dict with user information
        
    Raises:
        HTTPException: If authentication fails
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header format",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = authorization.split(" ")[1]
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return await auth_client.validate_token(token)


async def get_user_email(user: Dict = Depends(get_current_user)) -> str:
    """
    Extract user email from authenticated user info
    
    Args:
        user: User info from get_current_user
        
    Returns:
        User email string
    """
    # Extract email from subject or email field
    if "email" in user:
        return user["email"]
    elif user.get("subject", "").startswith("user:"):
        return user["subject"][5:]  # Remove "user:" prefix
    else:
        return "unknown@gnosis-crawl.local"
