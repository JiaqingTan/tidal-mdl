"""
Authentication module for Tidal MDL
Handles OAuth2 browser-based login and session management
"""

import json
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Tuple, Any
from dataclasses import dataclass, asdict
from concurrent.futures import Future

import tidalapi

from src.logger import logger


@dataclass
class OAuthLoginInfo:
    """Information needed to complete OAuth login in GUI"""
    auth_url: str
    user_code: str
    future: Any  # concurrent.futures.Future
    session: tidalapi.Session


@dataclass
class SessionData:
    """Stored session data for persistence"""
    token_type: str
    access_token: str
    refresh_token: str
    expiry_time: str  # ISO format datetime string
    user_id: Optional[int] = None
    country_code: Optional[str] = None
    
    def is_expired(self) -> bool:
        """Check if the access token is expired"""
        expiry = datetime.fromisoformat(self.expiry_time)
        # Add some buffer (5 minutes) before actual expiry
        return datetime.now() >= expiry - timedelta(minutes=5)
    
    @classmethod
    def from_session(cls, session: tidalapi.Session) -> "SessionData":
        """Create SessionData from an active tidalapi Session"""
        return cls(
            token_type=session.token_type,
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            expiry_time=session.expiry_time.isoformat() if session.expiry_time else "",
            user_id=session.user.id if session.user else None,
            country_code=session.country_code,
        )


def load_session(session_file: Path) -> Optional[SessionData]:
    """
    Load saved session from file
    
    Args:
        session_file: Path to the session JSON file
    
    Returns:
        SessionData if file exists and is valid, None otherwise
    """
    if not session_file.exists():
        return None
    
    try:
        with open(session_file, "r") as f:
            data = json.load(f)
        return SessionData(**data)
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        logger.warning(f"Could not load session file: {e}")
        return None


def save_session(session_data: SessionData, session_file: Path) -> None:
    """
    Save session data to file
    
    Args:
        session_data: SessionData to save
        session_file: Path to save the session JSON file
    """
    # Ensure directory exists
    session_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(session_file, "w") as f:
        json.dump(asdict(session_data), f, indent=2)
    
    # Set restrictive permissions (owner read/write only)
    session_file.chmod(0o600)


def delete_session(session_file: Path) -> None:
    """
    Delete saved session file
    
    Args:
        session_file: Path to the session file to delete
    """
    if session_file.exists():
        session_file.unlink()
        logger.info("Session deleted successfully.")


def create_session(quality: tidalapi.Quality = tidalapi.Quality.high_lossless) -> tidalapi.Session:
    """
    Create a new tidalapi Session with specified quality
    
    Args:
        quality: Audio quality setting
    
    Returns:
        New tidalapi.Session instance
    """
    config = tidalapi.Config(quality=quality)
    session = tidalapi.Session(config)
    return session


def restore_session(session: tidalapi.Session, session_data: SessionData) -> bool:
    """
    Restore a session from saved session data
    
    Args:
        session: tidalapi.Session to restore into
        session_data: Saved session data
    
    Returns:
        True if session restored successfully, False otherwise
    """
    try:
        # Convert expiry time back to datetime
        expiry_time = datetime.fromisoformat(session_data.expiry_time)
        
        # Load the session from stored tokens
        success = session.load_oauth_session(
            token_type=session_data.token_type,
            access_token=session_data.access_token,
            refresh_token=session_data.refresh_token,
            expiry_time=expiry_time,
        )
        
        return success and session.check_login()
    except Exception as e:
        logger.warning(f"Could not restore session: {e}")
        return False


def perform_oauth_login(session: tidalapi.Session, session_file: Path) -> bool:
    """
    Perform browser-based OAuth login
    
    Args:
        session: tidalapi.Session to authenticate
        session_file: Path to save session after successful login
    
    Returns:
        True if login successful, False otherwise
    """
    logger.info("Tidal Authentication Required")
    
    try:
        # Start OAuth flow
        login, future = session.login_oauth()
        
        # Display the login URL
        auth_url = f"https://{login.verification_uri_complete}"
        
        logger.info(f"Please visit this URL to log in: {auth_url}")
        logger.info(f"Or enter this code at https://link.tidal.com: {login.user_code}")
        
        # Try to open browser automatically
        try:
            webbrowser.open(auth_url)
            logger.info("Browser opened automatically. Please complete the login.")
        except Exception:
            logger.info("Please open the URL manually in your browser.")
        
        # Wait for authentication
        logger.info("Waiting for authentication...")
        future.result()  # This blocks until authentication completes
        logger.info("Authentication response received")
        
        # Check if login was successful
        if session.check_login():
            # Save session for future use
            session_data = SessionData.from_session(session)
            save_session(session_data, session_file)
            
            logger.info(f"Logged in as: {session.user.first_name} {session.user.last_name}")
            logger.info(f"Session saved to: {session_file}")
            return True
        else:
            logger.error("Login failed. Please try again.")
            return False
            
    except Exception as e:
        logger.error(f"Login error: {e}")
        return False


def get_authenticated_session(
    session_file: Path,
    quality: tidalapi.Quality = tidalapi.Quality.high_lossless,
    force_login: bool = False
) -> Optional[tidalapi.Session]:
    """
    Get an authenticated Tidal session, restoring from saved session or prompting for login
    
    Args:
        session_file: Path to the session file
        quality: Audio quality setting
        force_login: If True, ignore saved session and force new login
    
    Returns:
        Authenticated tidalapi.Session, or None if authentication failed
    """
    session = create_session(quality)
    
    # Try to restore existing session
    if not force_login:
        session_data = load_session(session_file)
        
        if session_data:
            logger.info("Found saved session, attempting to restore...")
            
            if restore_session(session, session_data):
                logger.info(f"Session restored successfully!")
                logger.info(f"Logged in as: {session.user.first_name} {session.user.last_name}")
                
                # Update saved session with potentially refreshed tokens
                new_session_data = SessionData.from_session(session)
                save_session(new_session_data, session_file)
                
                return session
            else:
                logger.warning("Saved session expired or invalid, need to re-authenticate.")
    
    # Perform new OAuth login
    if perform_oauth_login(session, session_file):
        return session
    
    return None


def start_oauth_flow(quality: tidalapi.Quality = tidalapi.Quality.high_lossless) -> Optional[OAuthLoginInfo]:
    """
    Start OAuth flow without blocking - returns info needed for GUI to display
    
    Args:
        quality: Audio quality setting
    
    Returns:
        OAuthLoginInfo with URL, code, and future to check, or None on error
    """
    try:
        session = create_session(quality)
        login, future = session.login_oauth()
        auth_url = f"https://{login.verification_uri_complete}"
        
        return OAuthLoginInfo(
            auth_url=auth_url,
            user_code=login.user_code,
            future=future,
            session=session
        )
    except Exception as e:
        logger.error(f"Failed to start OAuth flow: {e}")
        return None


def check_oauth_complete(login_info: OAuthLoginInfo, timeout: float = 0.1) -> Optional[tidalapi.Session]:
    """
    Check if OAuth flow completed (non-blocking)
    
    Args:
        login_info: OAuthLoginInfo from start_oauth_flow
        timeout: How long to wait before returning (default 0.1s for polling)
    
    Returns:
        Authenticated session if complete, None if still waiting or failed
    """
    try:
        # Check if future is done (non-blocking with short timeout)
        if login_info.future.done():
            # Get result (may raise exception if auth failed)
            login_info.future.result(timeout=0)
            
            if login_info.session.check_login():
                return login_info.session
        else:
            # Try to get result with short timeout
            try:
                login_info.future.result(timeout=timeout)
                if login_info.session.check_login():
                    return login_info.session
            except TimeoutError:
                pass  # Still waiting
    except Exception:
        pass  # Auth failed or other error
    
    return None


def complete_oauth_and_save(login_info: OAuthLoginInfo, session_file: Path) -> Optional[tidalapi.Session]:
    """
    Complete OAuth flow and save session
    
    Args:
        login_info: OAuthLoginInfo from start_oauth_flow
        session_file: Path to save session
    
    Returns:
        Authenticated session if successful, None otherwise
    """
    session = check_oauth_complete(login_info)
    if session:
        session_data = SessionData.from_session(session)
        save_session(session_data, session_file)
        return session
    return None

