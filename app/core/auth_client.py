"""
Authentication client for Grub Crawler to integrate with gnosis-auth service.
"""
import os
import logging
import requests
from typing import Dict, Any

logger = logging.getLogger(__name__)


class AuthClient:
    """Client for communicating with gnosis-auth service."""
    
    def __init__(self, auth_url: str):
        self.auth_url = auth_url.rstrip('/')
        
    def get_or_refresh_jwt(self, bearer_token: str, agent_id: str) -> Dict[str, Any]:
        """
        Get or refresh JWT from gnosis-auth service.
        
        Args:
            bearer_token: The HMAC bearer token
            agent_id: The agent ID
            
        Returns:
            Dict containing JWT and user information
        """
        try:
            response = requests.post(
                f"{self.auth_url}/api/auth/refresh",
                headers={"Authorization": f"Bearer {bearer_token}"},
                json={"agent_id": agent_id},
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"JWT refresh failed: {response.status_code} - {response.text}")
                raise Exception(f"JWT refresh failed: {response.status_code}")
                
        except requests.RequestException as e:
            logger.error(f"Error communicating with auth service: {e}")
            raise Exception(f"Auth service communication error: {e}")
    
    def validate_token(self, token: str) -> Dict[str, Any]:
        """
        Validate a token with gnosis-auth service.
        
        Args:
            token: The token to validate
            
        Returns:
            Dict containing user information
        """
        try:
            response = requests.post(
                f"{self.auth_url}/api/auth/validate",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Token validation failed: {response.status_code}")
                raise Exception(f"Token validation failed: {response.status_code}")
                
        except requests.RequestException as e:
            logger.error(f"Error validating token: {e}")
            raise Exception(f"Token validation error: {e}")


# Global auth client instance
_auth_client = None

def get_auth_client() -> AuthClient:
    """Get the global auth client instance."""
    global _auth_client
    if _auth_client is None:
        auth_url = os.getenv("GNOSIS_AUTH_URL", "http://gnosis-auth:5000")
        _auth_client = AuthClient(auth_url)
    return _auth_client