"""SoundCloud OAuth 2.1 authentication module.

Handles authorization code flow, token exchange, and refresh token management.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
import webbrowser
from pathlib import Path
from typing import Dict, Any
from urllib.parse import urlencode, parse_qs, urlparse

import requests

logger = logging.getLogger(__name__)

# SoundCloud OAuth endpoints
AUTH_URL = "https://soundcloud.com/connect"
TOKEN_URL = "https://api.soundcloud.com/oauth2/token"

# Token storage
TOKEN_FILE = Path.home() / ".autolive" / "sc_tokens.json"


def _ensure_token_dir() -> None:
    """Ensure the token directory exists with proper permissions."""
    TOKEN_FILE.parent.mkdir(mode=0o700, exist_ok=True)


def _load_tokens() -> Dict[str, Any] | None:
    """Load tokens from disk. Returns None if file doesn't exist or is invalid."""
    if not TOKEN_FILE.exists():
        return None
    
    try:
        with open(TOKEN_FILE, 'r') as f:
            data = json.load(f)
        
        # Check if tokens are expired
        if 'expires_at' in data and time.time() >= data['expires_at']:
            logger.info("Tokens expired, will need refresh")
            return data  # Return expired tokens for refresh
        
        return data
    except (json.JSONDecodeError, KeyError, OSError) as e:
        logger.warning(f"Failed to load tokens: {e}")
        return None


def _save_tokens(token_data: Dict[str, Any]) -> None:
    """Save tokens to disk with proper permissions."""
    _ensure_token_dir()
    
    # Add expiration timestamp
    if 'expires_in' in token_data:
        token_data['expires_at'] = time.time() + token_data['expires_in']
    
    with open(TOKEN_FILE, 'w') as f:
        json.dump(token_data, f, indent=2)
    
    # Set restrictive permissions
    TOKEN_FILE.chmod(0o600)
    logger.info("Tokens saved securely")


def _mask_token(token: str) -> str:
    """Mask token for logging (show last 6 chars only)."""
    if len(token) <= 6:
        return "*" * len(token)
    return "*" * (len(token) - 6) + token[-6:]


def authorize_and_exchange(client_id: str, client_secret: str, redirect_uri: str) -> Dict[str, Any]:
    """Perform OAuth 2.1 authorization code flow.
    
    Args:
        client_id: SoundCloud application client ID
        client_secret: SoundCloud application client secret  
        redirect_uri: Redirect URI (must match app settings)
        
    Returns:
        Token data dict with access_token, refresh_token, etc.
        
    Raises:
        RuntimeError: If authorization or token exchange fails
    """
    logger.info("Starting SoundCloud OAuth authorization")
    
    # Generate state parameter for CSRF protection
    state = secrets.token_urlsafe(32)
    
    # Build authorization URL
    auth_params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'non-expiring',
        'state': state
    }
    auth_url = f"{AUTH_URL}?{urlencode(auth_params)}"
    
    logger.info(f"Opening browser for authorization: {auth_url}")
    webbrowser.open(auth_url)
    
    # Start local server to capture callback
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading
    
    auth_code = None
    received_state = None
    
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal auth_code, received_state
            
            # Parse query parameters
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            
            if 'code' in params and 'state' in params:
                auth_code = params['code'][0]
                received_state = params['state'][0]
                
                # Send success response
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'''
                <html><body>
                <h1>Authorization Successful!</h1>
                <p>You can close this window and return to the terminal.</p>
                </body></html>
                ''')
            else:
                # Send error response
                self.send_response(400)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'''
                <html><body>
                <h1>Authorization Failed</h1>
                <p>Missing authorization code. Please try again.</p>
                </body></html>
                ''')
        
        def log_message(self, format, *args):
            # Suppress default logging
            pass
    
    # Start server
    server = HTTPServer(('127.0.0.1', 53682), CallbackHandler)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    
    logger.info("Waiting for authorization callback on http://127.0.0.1:53682/callback")
    
    # Wait for callback (with timeout)
    timeout = 300  # 5 minutes
    start_time = time.time()
    
    while auth_code is None and (time.time() - start_time) < timeout:
        time.sleep(1)
    
    server.shutdown()
    server.server_close()
    
    if auth_code is None:
        raise RuntimeError("Authorization timeout - no callback received")
    
    # Verify state parameter
    if received_state != state:
        raise RuntimeError("Invalid state parameter - possible CSRF attack")
    
    logger.info("Authorization code received, exchanging for tokens")
    
    # Exchange authorization code for tokens
    token_data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
        'code': auth_code
    }
    
    try:
        response = requests.post(TOKEN_URL, data=token_data, timeout=30)
        response.raise_for_status()
        
        token_response = response.json()
        logger.info(f"AUTH OK token={_mask_token(token_response['access_token'])}")
        
        _save_tokens(token_response)
        return token_response
        
    except requests.RequestException as e:
        logger.error(f"AUTH ERR: {e}")
        raise RuntimeError(f"Token exchange failed: {e}")


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> Dict[str, Any]:
    """Refresh an expired access token using refresh token.
    
    Args:
        client_id: SoundCloud application client ID
        client_secret: SoundCloud application client secret
        refresh_token: Valid refresh token
        
    Returns:
        New token data dict
        
    Raises:
        RuntimeError: If refresh fails
    """
    logger.info("Refreshing access token")
    
    token_data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token
    }
    
    try:
        response = requests.post(TOKEN_URL, data=token_data, timeout=30)
        response.raise_for_status()
        
        token_response = response.json()
        logger.info(f"AUTH REFRESH token={_mask_token(token_response['access_token'])}")
        
        _save_tokens(token_response)
        return token_response
        
    except requests.RequestException as e:
        logger.error(f"AUTH REFRESH ERR: {e}")
        raise RuntimeError(f"Token refresh failed: {e}")


def ensure_access_token(config: Dict[str, Any]) -> str:
    """Ensure we have a valid access token, refreshing if necessary.
    
    Args:
        config: Configuration dict with SoundCloud settings
        
    Returns:
        Valid access token string
        
    Raises:
        RuntimeError: If authentication fails
    """
    # Load existing tokens
    tokens = _load_tokens()
    
    if tokens is None:
        # No tokens - need full authorization
        logger.info("No existing tokens, starting authorization flow")
        tokens = authorize_and_exchange(
            config['client_id'],
            config['client_secret'], 
            config['redirect_uri']
        )
    elif 'expires_at' in tokens and time.time() >= tokens['expires_at']:
        # Tokens expired - refresh
        if 'refresh_token' not in tokens:
            raise RuntimeError("Tokens expired and no refresh token available")
        
        tokens = refresh_access_token(
            config['client_id'],
            config['client_secret'],
            tokens['refresh_token']
        )
    
    return tokens['access_token']