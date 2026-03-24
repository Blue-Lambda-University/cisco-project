"""OAuth2 client-credentials token acquisition."""

import logging
import time
import httpx
import os
from typing import Optional
from .properties import OAUTH_ENDPOINT

logger = logging.getLogger(__name__)


class OAuth2Client:
    """OAuth2 client for obtaining tokens to authenticate with sub-agents."""
    
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        token_url: Optional[str] = None,
        httpx_client: Optional[httpx.AsyncClient] = None
    ):
        self.client_id = client_id or os.environ.get('ORCHESTRATION_CLIENT_ID')
        self.client_secret = client_secret or os.environ.get('ORCHESTRATION_CLIENT_SECRET')
        self.token_url = token_url or OAUTH_ENDPOINT
        self.httpx_client = httpx_client or httpx.AsyncClient()
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._token_ttl: int = 3600  # Default 1 hour
    
    async def get_access_token(self, force_refresh: bool = False) -> Optional[str]:
        """
        Get a valid access token, refreshing if necessary.
        Returns None if token cannot be obtained.
        """
        if not self.client_id or not self.client_secret:
            logger.debug("OAuth2 client credentials not configured (this is OK for local testing)")
            return None
        
        # Check if we have a valid cached token
        if not force_refresh and self._access_token and time.time() < self._token_expires_at:
            return self._access_token
        
        # Refresh token
        try:
            logger.info("Obtaining new OAuth2 access token")
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            data = {
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'client_credentials'
            }
            
            response = await self.httpx_client.post(
                self.token_url,
                headers=headers,
                data=data,
                timeout=10.0
            )
            
            if response.status_code != 200:
                logger.error("Failed to obtain token: %s - %s", response.status_code, response.text)
                return None
            
            token_data = response.json()
            self._access_token = token_data.get('access_token')
            
            # Calculate expiration time
            expires_in = token_data.get('expires_in', self._token_ttl)
            self._token_expires_at = time.time() + expires_in - 60  # Refresh 1 minute early
            
            logger.info("Successfully obtained access token (expires in %ss)", expires_in)
            return self._access_token
            
        except Exception as e:
            logger.error("Error obtaining OAuth2 token: %s", e)
            return None
    
    async def get_auth_headers(self) -> dict:
        """
        Get authorization headers with bearer token.
        Returns empty dict if token unavailable.
        """
        token = await self.get_access_token()
        if not token:
            return {}
        
        return {'Authorization': f'Bearer {token}'}
    
    async def close(self) -> None:
        """Close the HTTP client."""
        await self.httpx_client.aclose()
