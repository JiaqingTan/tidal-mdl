"""
Authentication module for Tidal DL CLI
Handles OAuth2 browser-based login and session management
"""

import json
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Tuple
from dataclasses import dataclass, asdict

import tidalapi
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


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
        console.print(f"[yellow]Warning:[/yellow] Could not load session file: {e}")
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
        console.print("[green]Session deleted successfully.[/green]")


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
        console.print(f"[yellow]Warning:[/yellow] Could not restore session: {e}")
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
    console.print("\n[bold blue]🔐 Tidal Authentication Required[/bold blue]\n")
    
    try:
        # Start OAuth flow
        login, future = session.login_oauth()
        
        # Display the login URL
        auth_url = f"https://{login.verification_uri_complete}"
        
        console.print(Panel(
            f"[bold]Please visit this URL to log in:[/bold]\n\n"
            f"[link={auth_url}]{auth_url}[/link]\n\n"
            f"[dim]Or enter this code at [link=https://link.tidal.com]https://link.tidal.com[/link]:[/dim]\n"
            f"[bold cyan]{login.user_code}[/bold cyan]",
            title="🌐 Tidal Login",
            border_style="blue"
        ))
        
        # Try to open browser automatically
        try:
            webbrowser.open(auth_url)
            console.print("\n[dim]Browser opened automatically. Please complete the login.[/dim]")
        except Exception:
            console.print("\n[dim]Please open the URL manually in your browser.[/dim]")
        
        # Wait for authentication with spinner
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Waiting for authentication...", total=None)
            future.result()  # This blocks until authentication completes
            progress.update(task, description="[green]✓ Authentication successful!")
        
        # Check if login was successful
        if session.check_login():
            # Save session for future use
            session_data = SessionData.from_session(session)
            save_session(session_data, session_file)
            
            console.print(f"\n[green]✓ Logged in as:[/green] {session.user.first_name} {session.user.last_name}")
            console.print(f"[dim]Session saved to: {session_file}[/dim]\n")
            return True
        else:
            console.print("\n[red]✗ Login failed. Please try again.[/red]")
            return False
            
    except Exception as e:
        console.print(f"\n[red]✗ Login error: {e}[/red]")
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
            console.print("[dim]Found saved session, attempting to restore...[/dim]")
            
            if restore_session(session, session_data):
                console.print(f"[green]✓ Session restored successfully![/green]")
                console.print(f"[dim]Logged in as: {session.user.first_name} {session.user.last_name}[/dim]\n")
                
                # Update saved session with potentially refreshed tokens
                new_session_data = SessionData.from_session(session)
                save_session(new_session_data, session_file)
                
                return session
            else:
                console.print("[yellow]Saved session expired or invalid, need to re-authenticate.[/yellow]")
    
    # Perform new OAuth login
    if perform_oauth_login(session, session_file):
        return session
    
    return None
