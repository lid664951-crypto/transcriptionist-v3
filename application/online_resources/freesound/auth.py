"""
Freesound Authentication

Implements OAuth2 authentication flow for Freesound API.

For most operations (search, download), Token authentication is sufficient.
OAuth2 is required for operations that modify user data (upload, bookmark, etc.).

OAuth2 Flow:
1. Redirect user to Freesound authorization URL
2. User grants permission
3. Freesound redirects back with authorization code
4. Exchange code for access token
5. Use access token for API requests

API Documentation: https://freesound.org/docs/api/authentication.html
"""

import asyncio
import logging
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable
from urllib.parse import urlencode, parse_qs, urlparse
import aiohttp
import json
from pathlib import Path

logger = logging.getLogger(__name__)

# Freesound OAuth endpoints
AUTHORIZE_URL = "https://freesound.org/apiv2/oauth2/authorize/"
TOKEN_URL = "https://freesound.org/apiv2/oauth2/access_token/"


@dataclass
class FreesoundCredentials:
    """
    Freesound API credentials.
    
    For Token authentication, only api_token is needed.
    For OAuth2, client_id and client_secret are also required.
    """
    
    api_token: str = ""
    client_id: str = ""
    client_secret: str = ""
    access_token: str = ""
    refresh_token: str = ""
    token_expires_at: Optional[datetime] = None
    
    @property
    def is_token_valid(self) -> bool:
        """Check if OAuth access token is still valid."""
        if not self.access_token:
            return False
        if self.token_expires_at is None:
            return True
        return datetime.now() < self.token_expires_at
    
    @property
    def has_oauth(self) -> bool:
        """Check if OAuth credentials are configured."""
        return bool(self.client_id and self.client_secret)
    
    @property
    def effective_token(self) -> str:
        """Get the token to use for API requests."""
        if self.is_token_valid and self.access_token:
            return self.access_token
        return self.api_token
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            'api_token': self.api_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'token_expires_at': self.token_expires_at.isoformat() if self.token_expires_at else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FreesoundCredentials':
        """Create from dictionary."""
        expires_at = None
        if data.get('token_expires_at'):
            try:
                expires_at = datetime.fromisoformat(data['token_expires_at'])
            except (ValueError, TypeError):
                pass
        
        return cls(
            api_token=data.get('api_token', ''),
            client_id=data.get('client_id', ''),
            client_secret=data.get('client_secret', ''),
            access_token=data.get('access_token', ''),
            refresh_token=data.get('refresh_token', ''),
            token_expires_at=expires_at,
        )
    
    def save(self, path: Path) -> None:
        """Save credentials to file."""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load(cls, path: Path) -> 'FreesoundCredentials':
        """Load credentials from file."""
        if not path.exists():
            return cls()
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls.from_dict(data)


class FreesoundOAuth:
    """
    Handles OAuth2 authentication flow for Freesound.
    
    Usage:
        oauth = FreesoundOAuth(credentials)
        
        # Start authorization
        auth_url = oauth.get_authorization_url(redirect_uri)
        # User visits auth_url and grants permission
        
        # After redirect, exchange code for token
        await oauth.exchange_code(code, redirect_uri)
        
        # Now credentials.access_token is set
    """
    
    def __init__(self, credentials: FreesoundCredentials):
        """
        Initialize OAuth handler.
        
        Args:
            credentials: FreesoundCredentials with client_id and client_secret
        """
        self.credentials = credentials
    
    def get_authorization_url(
        self,
        redirect_uri: str,
        state: Optional[str] = None,
    ) -> str:
        """
        Get the URL to redirect user for authorization.
        
        Args:
            redirect_uri: URL to redirect after authorization
            state: Optional state parameter for CSRF protection
        
        Returns:
            Authorization URL
        """
        params = {
            'client_id': self.credentials.client_id,
            'response_type': 'code',
            'redirect_uri': redirect_uri,
        }
        
        if state:
            params['state'] = state
        
        return f"{AUTHORIZE_URL}?{urlencode(params)}"
    
    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
    ) -> bool:
        """
        Exchange authorization code for access token.
        
        Args:
            code: Authorization code from redirect
            redirect_uri: Same redirect URI used in authorization
        
        Returns:
            True if successful
        """
        data = {
            'client_id': self.credentials.client_id,
            'client_secret': self.credentials.client_secret,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(TOKEN_URL, data=data) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.error(f"Token exchange failed: {text}")
                    return False
                
                result = await response.json()
                self._update_tokens(result)
                return True
    
    async def refresh_access_token(self) -> bool:
        """
        Refresh the access token using refresh token.
        
        Returns:
            True if successful
        """
        if not self.credentials.refresh_token:
            logger.error("No refresh token available")
            return False
        
        data = {
            'client_id': self.credentials.client_id,
            'client_secret': self.credentials.client_secret,
            'grant_type': 'refresh_token',
            'refresh_token': self.credentials.refresh_token,
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(TOKEN_URL, data=data) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.error(f"Token refresh failed: {text}")
                    return False
                
                result = await response.json()
                self._update_tokens(result)
                return True
    
    def _update_tokens(self, token_response: Dict[str, Any]) -> None:
        """Update credentials with token response."""
        self.credentials.access_token = token_response.get('access_token', '')
        self.credentials.refresh_token = token_response.get('refresh_token', self.credentials.refresh_token)
        
        expires_in = token_response.get('expires_in')
        if expires_in:
            self.credentials.token_expires_at = datetime.now() + timedelta(seconds=int(expires_in))
        
        logger.info("OAuth tokens updated successfully")
    
    async def ensure_valid_token(self) -> bool:
        """
        Ensure we have a valid access token, refreshing if needed.
        
        Returns:
            True if we have a valid token
        """
        if self.credentials.is_token_valid:
            return True
        
        if self.credentials.refresh_token:
            return await self.refresh_access_token()
        
        return False


class LocalOAuthServer:
    """
    Simple local HTTP server for OAuth callback.
    
    This allows desktop applications to receive the OAuth callback
    without requiring a public redirect URI.
    """
    
    def __init__(self, port: int = 8765):
        """
        Initialize local OAuth server.
        
        Args:
            port: Port to listen on
        """
        self.port = port
        self.redirect_uri = f"http://localhost:{port}/callback"
        self._code: Optional[str] = None
        self._state: Optional[str] = None
        self._error: Optional[str] = None
    
    async def wait_for_callback(self, timeout: float = 300) -> Optional[str]:
        """
        Start server and wait for OAuth callback.
        
        Args:
            timeout: Maximum time to wait in seconds
        
        Returns:
            Authorization code if received, None otherwise
        """
        from aiohttp import web
        
        async def handle_callback(request: web.Request) -> web.Response:
            self._code = request.query.get('code')
            self._state = request.query.get('state')
            self._error = request.query.get('error')
            
            if self._error:
                html = f"""
                <html><body>
                <h1>Authorization Failed</h1>
                <p>Error: {self._error}</p>
                <p>You can close this window.</p>
                </body></html>
                """
            else:
                html = """
                <html><body>
                <h1>Authorization Successful</h1>
                <p>You can close this window and return to the application.</p>
                </body></html>
                """
            
            return web.Response(text=html, content_type='text/html')
        
        app = web.Application()
        app.router.add_get('/callback', handle_callback)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', self.port)
        
        try:
            await site.start()
            logger.info(f"OAuth callback server started on port {self.port}")
            
            # Wait for callback or timeout
            start_time = asyncio.get_event_loop().time()
            while self._code is None and self._error is None:
                if asyncio.get_event_loop().time() - start_time > timeout:
                    logger.warning("OAuth callback timeout")
                    return None
                await asyncio.sleep(0.1)
            
            return self._code
        
        finally:
            await runner.cleanup()


async def authorize_with_browser(
    credentials: FreesoundCredentials,
    port: int = 8765,
    timeout: float = 300,
) -> bool:
    """
    Perform OAuth authorization using the system browser.
    
    This opens the browser for user authorization and waits for the callback.
    
    Args:
        credentials: FreesoundCredentials with client_id and client_secret
        port: Local port for callback server
        timeout: Maximum time to wait for authorization
    
    Returns:
        True if authorization successful
    """
    if not credentials.has_oauth:
        logger.error("OAuth credentials not configured")
        return False
    
    oauth = FreesoundOAuth(credentials)
    server = LocalOAuthServer(port)
    
    # Get authorization URL
    auth_url = oauth.get_authorization_url(server.redirect_uri)
    
    # Open browser
    logger.info(f"Opening browser for authorization: {auth_url}")
    webbrowser.open(auth_url)
    
    # Wait for callback
    code = await server.wait_for_callback(timeout)
    
    if not code:
        logger.error("No authorization code received")
        return False
    
    # Exchange code for token
    return await oauth.exchange_code(code, server.redirect_uri)
