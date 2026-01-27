#!/usr/bin/env python3
"""
Tidal MDL - Modern GUI Application
A beautiful desktop app for downloading Tidal music
"""

import sys
import os
import threading
from pathlib import Path
from typing import Optional, List, Dict, Callable
from io import BytesIO

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

import customtkinter as ctk
from PIL import Image
import requests

from src.config import Config, load_config
from src.auth import (
    get_authenticated_session, delete_session,
    start_oauth_flow, check_oauth_complete, complete_oauth_and_save,
    OAuthLoginInfo
)
from src.search import search, SearchType, SearchResult
from src.downloader import (
    DownloadQueue, DownloadTask, DownloadStatus,
    create_album_tasks, create_track_task,
)
from src.logger import logger

# ============================================================================
# Configure CustomTkinter
# ============================================================================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Professional color palette - muted, sophisticated tones
COLORS = {
    "bg_dark": "#1a1d21",      # Deep charcoal
    "bg_medium": "#252a31",    # Dark slate
    "bg_light": "#353d47",     # Medium slate
    "accent": "#6e8efb",       # Soft blue
    "accent_hover": "#8ba3fc", # Light blue
    "green": "#5cb85c",        # Muted green
    "red": "#d9534f",          # Muted red
    "yellow": "#f0ad4e",       # Muted amber
    "blue": "#5bc0de",         # Soft cyan
    "text": "#e8eaed",         # Near-white
    "subtext": "#9aa0a6",      # Gray
    "border": "#404952",       # Border gray
}

# Font family (uses system fonts)
FONT_FAMILY = "SF Pro Display"  # macOS default, falls back gracefully


class TidalMDLApp(ctk.CTk):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        
        # Window setup
        self.title("Tidal MDL")
        self.geometry("1100x750")
        self.configure(fg_color=COLORS["bg_dark"])
        
        # State
        self.config = load_config()
        self.session = None
        self.download_queue = None
        self.expanded_albums = {}  # Track which albums are expanded (album_id -> bool)
        
        # Widget tracking for incremental updates (prevents flashing)
        self._download_widgets = {}  # task_id -> {frame, status_label, progress_bar, icon_label}
        self._album_widgets = {}  # album_id -> {header, progress_bar, progress_label, thumb_label}
        self._last_task_ids = set()  # Track task IDs from last refresh
        
        # Image cache to prevent memory leaks and improve performance
        # LRU cache with max 100 images
        self._image_cache = {}
        self._image_cache_order = []
        self._max_cached_images = 100
        
        # Thread pool for image loading (limit concurrent downloads)
        from concurrent.futures import ThreadPoolExecutor
        self._image_executor = ThreadPoolExecutor(max_workers=5)
        
        # Search state for pagination
        self.search_results = None
        self.search_query = ""  # Current search query
        self.albums_page = 0
        self.tracks_page = 0
        self.playlists_page = 0
        self.ALBUMS_PER_PAGE = 8
        self.TRACKS_PER_PAGE = 10
        self.PLAYLISTS_PER_PAGE = 6
        self.API_FETCH_LIMIT = 50  # Fetch 50 at a time from API
        # Track if more results might be available
        self.albums_has_more = True
        self.tracks_has_more = True
        self.playlists_has_more = True
        
        # Build UI
        self._build_ui()
        
        # Start auth
        self.after(500, self._authenticate)
    
    def _load_image_async(self, url, size, callback, cache_key=None):
        """Load an image asynchronously with caching and thread pool"""
        if not url:
            return
        
        cache_key = cache_key or f"{url}_{size[0]}x{size[1]}"
        
        # Check cache first
        if cache_key in self._image_cache:
            # Move to end of order (most recently used)
            if cache_key in self._image_cache_order:
                self._image_cache_order.remove(cache_key)
            self._image_cache_order.append(cache_key)
            ctk_img = self._image_cache[cache_key]
            self.after(0, lambda: callback(ctk_img))
            return
        
        def fetch_image():
            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    img = Image.open(BytesIO(resp.content))
                    img = img.resize(size, Image.Resampling.LANCZOS)
                    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=size)
                    
                    # Cache the image
                    self._image_cache[cache_key] = ctk_img
                    self._image_cache_order.append(cache_key)
                    
                    # Evict oldest if over limit
                    while len(self._image_cache_order) > self._max_cached_images:
                        oldest = self._image_cache_order.pop(0)
                        if oldest in self._image_cache:
                            del self._image_cache[oldest]
                    
                    self.after(0, lambda: callback(ctk_img))
            except Exception:
                pass  # Silently fail for images
        
        # Submit to thread pool instead of creating new thread
        self._image_executor.submit(fetch_image)
    
    def _build_ui(self):
        """Build the main UI"""
        # Configure main grid
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # === SIDEBAR ===
        sidebar = ctk.CTkFrame(self, width=200, corner_radius=0, fg_color=COLORS["bg_medium"])
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        
        # Logo
        logo = ctk.CTkLabel(
            sidebar, 
            text="TIDAL MDL",
            font=ctk.CTkFont(family=FONT_FAMILY, size=20, weight="bold"),
            text_color=COLORS["accent"]
        )
        logo.pack(pady=(35, 45), padx=20)
        
        # Navigation
        self.nav_search = ctk.CTkButton(
            sidebar, text="Search", anchor="w", height=42,
            fg_color=COLORS["bg_light"], hover_color=COLORS["accent"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            corner_radius=6,
            command=lambda: self._show_view("search")
        )
        self.nav_search.pack(fill="x", padx=12, pady=4)
        
        self.nav_downloads = ctk.CTkButton(
            sidebar, text="Downloads", anchor="w", height=42,
            fg_color="transparent", hover_color=COLORS["accent"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            corner_radius=6,
            command=lambda: self._show_view("downloads")
        )
        self.nav_downloads.pack(fill="x", padx=12, pady=4)
        
        self.nav_settings = ctk.CTkButton(
            sidebar, text="Settings", anchor="w", height=42,
            fg_color="transparent", hover_color=COLORS["accent"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=13),
            corner_radius=6,
            command=lambda: self._show_view("settings")
        )
        self.nav_settings.pack(fill="x", padx=12, pady=4)
        
        # Spacer
        ctk.CTkFrame(sidebar, fg_color="transparent").pack(fill="both", expand=True)
        
        # Status
        self.status_label = ctk.CTkLabel(
            sidebar, text="Connecting...",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=COLORS["subtext"]
        )
        self.status_label.pack(pady=10)
        
        # Logout
        ctk.CTkButton(
            sidebar, text="Sign Out", height=36,
            fg_color=COLORS["bg_light"], hover_color=COLORS["red"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            corner_radius=6,
            command=self._logout
        ).pack(fill="x", padx=12, pady=(5, 20))
        
        # === MAIN CONTENT ===
        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color=COLORS["bg_dark"])
        self.content.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        
        # Create views
        self.views = {}
        self._create_search_view()
        self._create_downloads_view()
        self._create_settings_view()
        
        # Show default
        self._show_view("search")
    
    def _create_search_view(self):
        """Create search view"""
        view = ctk.CTkFrame(self.content, fg_color="transparent")
        
        # Header
        header = ctk.CTkFrame(view, fg_color="transparent")
        header.pack(fill="x", padx=30, pady=(30, 20))
        
        # Search box
        self.search_entry = ctk.CTkEntry(
            header,
            placeholder_text="Search for albums, tracks, artists...",
            height=45,
            font=ctk.CTkFont(size=15),
            fg_color=COLORS["bg_medium"],
            border_color=COLORS["bg_light"]
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.search_entry.bind("<Return>", lambda e: self._do_search())
        
        ctk.CTkButton(
            header, text="Search", width=100, height=45,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["bg_dark"],
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._do_search
        ).pack(side="right")
        
        # My Playlists button
        ctk.CTkButton(
            header, text="My Playlists", width=110, height=45,
            fg_color=COLORS["bg_light"], hover_color=COLORS["accent"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=13),
            command=self._load_my_playlists
        ).pack(side="right", padx=(0, 10))
        
        # Results
        self.results_frame = ctk.CTkScrollableFrame(
            view, fg_color="transparent",
            scrollbar_button_color=COLORS["bg_light"]
        )
        self.results_frame.pack(fill="both", expand=True, padx=30, pady=(0, 20))
        
        # Placeholder
        self.search_placeholder = ctk.CTkLabel(
            self.results_frame,
            text="Search for music above\nor click 'My Playlists' for your personal playlists",
            font=ctk.CTkFont(size=16),
            text_color=COLORS["subtext"],
            justify="center"
        )
        self.search_placeholder.pack(pady=100)
        
        self.views["search"] = view
    
    def _create_downloads_view(self):
        """Create downloads view"""
        view = ctk.CTkFrame(self.content, fg_color="transparent")
        
        # Header
        header = ctk.CTkFrame(view, fg_color="transparent")
        header.pack(fill="x", padx=30, pady=(30, 20))
        
        ctk.CTkLabel(
            header, text="Downloads",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=COLORS["text"]
        ).pack(side="left")
        
        # Buttons
        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.pack(side="right")
        
        ctk.CTkButton(
            btn_frame, text="Start", width=80, height=35,
            fg_color=COLORS["green"], hover_color="#8bd48b",
            text_color=COLORS["bg_dark"],
            command=self._start_downloads
        ).pack(side="left", padx=3)
        
        ctk.CTkButton(
            btn_frame, text="Stop", width=80, height=35,
            fg_color=COLORS["yellow"], hover_color="#d9a340",
            text_color=COLORS["bg_dark"],
            command=self._stop_downloads
        ).pack(side="left", padx=3)
        
        ctk.CTkButton(
            btn_frame, text="Clear", width=80, height=35,
            fg_color=COLORS["bg_light"], hover_color=COLORS["red"],
            text_color=COLORS["text"],
            command=self._clear_downloads
        ).pack(side="left", padx=3)
        
        # Stats bar
        stats = ctk.CTkFrame(view, fg_color=COLORS["bg_medium"], corner_radius=10)
        stats.pack(fill="x", padx=30, pady=(0, 15))
        
        stats_inner = ctk.CTkFrame(stats, fg_color="transparent")
        stats_inner.pack(pady=12)
        
        self.stat_queued = self._create_stat(stats_inner, "0", "Queued", COLORS["subtext"])
        self.stat_active = self._create_stat(stats_inner, "0", "Active", COLORS["blue"])
        self.stat_done = self._create_stat(stats_inner, "0", "Done", COLORS["green"])
        self.stat_failed = self._create_stat(stats_inner, "0", "Failed", COLORS["red"])
        
        # Downloads list
        self.downloads_list = ctk.CTkScrollableFrame(
            view, fg_color="transparent",
            scrollbar_button_color=COLORS["bg_light"]
        )
        self.downloads_list.pack(fill="both", expand=True, padx=30, pady=(0, 20))
        
        # Placeholder
        ctk.CTkLabel(
            self.downloads_list,
            text="No downloads yet\nSearch and add music to queue",
            font=ctk.CTkFont(size=14),
            text_color=COLORS["subtext"]
        ).pack(pady=80)
        
        self.views["downloads"] = view
    
    def _create_stat(self, parent, value, label, color):
        """Create a stat display"""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(side="left", padx=25)
        
        val = ctk.CTkLabel(frame, text=value, font=ctk.CTkFont(size=24, weight="bold"), text_color=color)
        val.pack()
        ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=11), text_color=COLORS["subtext"]).pack()
        
        return val
    
    def _create_settings_view(self):
        """Create settings view"""
        view = ctk.CTkFrame(self.content, fg_color="transparent")
        
        # Store settings widgets for saving
        self.settings_widgets = {}
        
        # Header
        ctk.CTkLabel(
            view, text="Settings",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=COLORS["text"]
        ).pack(padx=30, pady=(30, 20), anchor="w")
        
        # Settings scroll
        scroll = ctk.CTkScrollableFrame(view, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=30, pady=(0, 20))
        
        # Quality section
        self._add_section(scroll, "Quality")
        self.settings_widgets["download_quality"] = self._add_option(
            scroll, "Download Quality", 
            ["HI_RES", "LOSSLESS", "HIGH", "NORMAL"], 
            self._quality_to_str(self.config.download_quality)
        )
        
        # Download section
        self._add_section(scroll, "Downloads")
        self.settings_widgets["download_folder"] = self._add_folder_option(
            scroll, "Download Folder", str(self.config.download_folder)
        )
        self.settings_widgets["max_concurrent"] = self._add_text_option(
            scroll, "Max Concurrent", str(self.config.max_concurrent_downloads)
        )
        
        # Folder Templates section
        self._add_section(scroll, "Folder & File Templates")
        self.settings_widgets["album_folder_template"] = self._add_text_option(
            scroll, "Album Folder", self.config.album_folder_template,
            hint="{artist}, {album}, {year}, {quality}"
        )
        self.settings_widgets["track_file_template"] = self._add_text_option(
            scroll, "Track Filename", self.config.track_file_template,
            hint="{track_number}, {title}, {artist}"
        )
        self.settings_widgets["album_art_filename"] = self._add_text_option(
            scroll, "Album Art Filename", self.config.album_art_filename
        )
        
        # Metadata section
        self._add_section(scroll, "Metadata")
        self.settings_widgets["embed_album_art"] = self._add_toggle(
            scroll, "Embed Album Art", self.config.embed_album_art
        )
        self.settings_widgets["save_album_art"] = self._add_toggle(
            scroll, "Save Album Art", self.config.save_album_art
        )
        self.settings_widgets["embed_lyrics"] = self._add_toggle(
            scroll, "Embed Lyrics", self.config.embed_lyrics
        )
        self.settings_widgets["skip_existing"] = self._add_toggle(
            scroll, "Skip Existing Files", self.config.skip_existing
        )
        
        # Playlist Settings section
        self._add_section(scroll, "Playlist Settings")
        self.settings_widgets["playlist_album_artist"] = self._add_text_option(
            scroll, "Album Artist for Playlists (e.g. Various Artists, VA)", 
            self.config.playlist_album_artist,
            hint="Used when downloading playlists 'As One'"
        )
        
        # Save button
        ctk.CTkButton(
            view, text="Save Settings", height=45,
            fg_color=COLORS["green"], hover_color="#8bd48b",
            text_color=COLORS["bg_dark"],
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._save_settings
        ).pack(fill="x", padx=30, pady=20)
        
        self.views["settings"] = view
    
    def _quality_to_str(self, quality):
        """Convert quality enum to string"""
        import tidalapi
        quality_map = {
            tidalapi.Quality.low_96k: "NORMAL",
            tidalapi.Quality.low_320k: "HIGH",
            tidalapi.Quality.high_lossless: "LOSSLESS",
            tidalapi.Quality.hi_res_lossless: "HI_RES",
        }
        return quality_map.get(quality, "LOSSLESS")
    
    def _add_section(self, parent, title):
        """Add a section header"""
        ctk.CTkLabel(
            parent, text=title,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS["accent"]
        ).pack(anchor="w", pady=(20, 10))
    
    def _add_option(self, parent, label, options, default):
        """Add a dropdown option, returns the option menu widget"""
        frame = ctk.CTkFrame(parent, fg_color=COLORS["bg_medium"], corner_radius=8)
        frame.pack(fill="x", pady=3)
        
        ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=13)).pack(side="left", padx=15, pady=12)
        option_menu = ctk.CTkOptionMenu(
            frame, values=options, width=150,
            fg_color=COLORS["bg_light"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"]
        )
        option_menu.set(default)
        option_menu.pack(side="right", padx=15, pady=12)
        return option_menu
    
    def _add_text_option(self, parent, label, default, hint=None):
        """Add a text input option, returns the entry widget"""
        frame = ctk.CTkFrame(parent, fg_color=COLORS["bg_medium"], corner_radius=8)
        frame.pack(fill="x", pady=3)
        
        # Label section
        label_frame = ctk.CTkFrame(frame, fg_color="transparent")
        label_frame.pack(side="left", padx=15, pady=10)
        
        ctk.CTkLabel(label_frame, text=label, font=ctk.CTkFont(family=FONT_FAMILY, size=13)).pack(anchor="w")
        
        if hint:
            ctk.CTkLabel(
                label_frame, text=hint,
                font=ctk.CTkFont(family=FONT_FAMILY, size=9),
                text_color=COLORS["subtext"]
            ).pack(anchor="w")
        
        entry = ctk.CTkEntry(frame, width=250, fg_color=COLORS["bg_light"])
        entry.insert(0, default)
        entry.pack(side="right", padx=15, pady=10)
        return entry
    
    def _add_toggle(self, parent, label, default):
        """Add a toggle option, returns the switch widget"""
        frame = ctk.CTkFrame(parent, fg_color=COLORS["bg_medium"], corner_radius=8)
        frame.pack(fill="x", pady=3)
        
        ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=13)).pack(side="left", padx=15, pady=12)
        switch = ctk.CTkSwitch(frame, text="", fg_color=COLORS["bg_light"], progress_color=COLORS["green"])
        if default:
            switch.select()
        switch.pack(side="right", padx=15, pady=12)
        return switch
    
    def _add_folder_option(self, parent, label, default):
        """Add a folder picker option, returns the entry widget"""
        from tkinter import filedialog
        
        frame = ctk.CTkFrame(parent, fg_color=COLORS["bg_medium"], corner_radius=8)
        frame.pack(fill="x", pady=3)
        
        ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=13)).pack(side="left", padx=15, pady=12)
        
        # Entry to show current path
        entry = ctk.CTkEntry(frame, width=250, fg_color=COLORS["bg_light"])
        entry.insert(0, default)
        entry.pack(side="right", padx=(0, 15), pady=12)
        
        # Browse button
        def browse():
            folder = filedialog.askdirectory(
                title="Select Download Folder",
                initialdir=default
            )
            if folder:
                entry.delete(0, "end")
                entry.insert(0, folder)
        
        ctk.CTkButton(
            frame, text="...", width=40, height=30,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["bg_dark"],
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            command=browse
        ).pack(side="right", padx=5, pady=12)
        
        return entry
    
    def _show_view(self, name):
        """Show a view"""
        # Hide all
        for v in self.views.values():
            v.grid_forget()
        
        # Update nav buttons
        self.nav_search.configure(fg_color="transparent")
        self.nav_downloads.configure(fg_color="transparent")
        self.nav_settings.configure(fg_color="transparent")
        
        if name == "search":
            self.nav_search.configure(fg_color=COLORS["bg_light"])
        elif name == "downloads":
            self.nav_downloads.configure(fg_color=COLORS["bg_light"])
        elif name == "settings":
            self.nav_settings.configure(fg_color=COLORS["bg_light"])
        
        # Show selected
        self.views[name].grid(row=0, column=0, sticky="nsew")
    
    def _authenticate(self):
        """Authenticate with Tidal - tries saved session first, then shows login dialog if needed"""
        self.status_label.configure(text="Connecting...", text_color=COLORS["subtext"])
        
        def auth_thread():
            try:
                # First try to restore existing session
                self.session = get_authenticated_session(
                    self.config.session_file,
                    self.config.download_quality,
                    force_login=False
                )
                if self.session:
                    self.download_queue = DownloadQueue(self.config, self.session)
                    self.after(0, lambda: self.status_label.configure(
                        text="Connected", text_color=COLORS["green"]
                    ))
                else:
                    # Session restore failed, need to show login dialog
                    self.after(0, self._show_login_dialog)
            except Exception as e:
                logger.exception("Auth error")
                # Show login dialog on any error
                self.after(0, self._show_login_dialog)
        
        threading.Thread(target=auth_thread, daemon=True).start()
    
    def _show_login_dialog(self):
        """Show a login dialog with OAuth URL and code"""
        import webbrowser
        
        # Start OAuth flow
        login_info = start_oauth_flow(self.config.download_quality)
        if not login_info:
            self.status_label.configure(text="Login failed", text_color=COLORS["red"])
            return
        
        # Create login dialog
        dialog = ctk.CTkToplevel(self)
        dialog.title("Sign In to Tidal")
        dialog.geometry("450x320")
        dialog.configure(fg_color=COLORS["bg_dark"])
        dialog.transient(self)
        dialog.grab_set()
        
        # Center on parent
        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - (225)
        y = self.winfo_y() + (self.winfo_height() // 2) - (160)
        dialog.geometry(f"+{x}+{y}")
        
        # Title
        ctk.CTkLabel(
            dialog, text="🔐 Sign In Required",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["text"]
        ).pack(pady=(25, 15))
        
        # Instructions
        ctk.CTkLabel(
            dialog, text="Complete login in your browser, or enter the code at link.tidal.com",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["subtext"],
            wraplength=400
        ).pack(pady=(0, 15))
        
        # Code display
        code_frame = ctk.CTkFrame(dialog, fg_color=COLORS["bg_medium"], corner_radius=8)
        code_frame.pack(padx=30, pady=10, fill="x")
        
        ctk.CTkLabel(
            code_frame, text="Your Code:",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["subtext"]
        ).pack(pady=(10, 0))
        
        ctk.CTkLabel(
            code_frame, text=login_info.user_code,
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=COLORS["accent"]
        ).pack(pady=(5, 10))
        
        # Buttons
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=15)
        
        def open_browser():
            webbrowser.open(login_info.auth_url)
        
        def copy_link():
            self.clipboard_clear()
            self.clipboard_append(login_info.auth_url)
            copy_btn.configure(text="Copied!")
            dialog.after(1500, lambda: copy_btn.configure(text="Copy Link"))
        
        ctk.CTkButton(
            btn_frame, text="Open Browser", width=130, height=38,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["bg_dark"],
            font=ctk.CTkFont(size=13, weight="bold"),
            command=open_browser
        ).pack(side="left", padx=5)
        
        copy_btn = ctk.CTkButton(
            btn_frame, text="Copy Link", width=110, height=38,
            fg_color=COLORS["bg_light"], hover_color=COLORS["bg_medium"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=13),
            command=copy_link
        )
        copy_btn.pack(side="left", padx=5)
        
        # Status
        status_label = ctk.CTkLabel(
            dialog, text="Waiting for login...",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["subtext"]
        )
        status_label.pack(pady=(5, 15))
        
        # Poll for auth completion
        def check_auth():
            session = check_oauth_complete(login_info, timeout=0.5)
            if session:
                # Save session and update app
                from src.auth import SessionData, save_session
                session_data = SessionData.from_session(session)
                save_session(session_data, self.config.session_file)
                
                self.session = session
                self.download_queue = DownloadQueue(self.config, self.session)
                self.status_label.configure(text="Connected", text_color=COLORS["green"])
                dialog.destroy()
            elif dialog.winfo_exists():
                # Keep polling
                dialog.after(1000, check_auth)
        
        # Start polling after opening browser automatically
        open_browser()
        dialog.after(2000, check_auth)
    
    def _logout(self):
        """Logout"""
        delete_session(self.config.session_file)
        self.session = None
        self.status_label.configure(text="Connecting...", text_color=COLORS["subtext"])
        self._authenticate()
    
    def _do_search(self):
        """Execute search"""
        query = self.search_entry.get().strip()
        if not query or not self.session:
            return
        
        # Reset pagination and lazy loading state
        self.search_query = query
        self.albums_page = 0
        self.tracks_page = 0
        self.playlists_page = 0
        self.albums_has_more = True
        self.tracks_has_more = True
        self.playlists_has_more = True
        self.search_results = SearchResult([], [], [], [], [])  # Empty result container
        
        # Clear results
        for w in self.results_frame.winfo_children():
            w.destroy()
        
        # Show loading
        loading = ctk.CTkLabel(
            self.results_frame, text="Searching...",
            font=ctk.CTkFont(size=16), text_color=COLORS["subtext"]
        )
        loading.pack(pady=100)
        
        def search_thread():
            try:
                results = search(self.session, query, limit=self.API_FETCH_LIMIT)
                # Check if we got less than the limit (meaning no more results)
                self.albums_has_more = len(results.albums) >= self.API_FETCH_LIMIT
                self.tracks_has_more = len(results.tracks) >= self.API_FETCH_LIMIT
                self.playlists_has_more = len(results.playlists) >= self.API_FETCH_LIMIT
                self.search_results = results
                self.after(0, lambda: self._display_results(results))
            except Exception as e:
                logger.exception("Search error")
                self.after(0, lambda: self._show_error(f"Search failed: {e}"))
        
        threading.Thread(target=search_thread, daemon=True).start()
    
    def _load_my_playlists(self):
        """Load user's personal playlists"""
        if not self.session:
            self._show_toast("Not connected", COLORS["red"])
            return
        
        # Reset state
        self.playlists_page = 0
        self.playlists_has_more = False  # User playlists are loaded all at once
        
        # Clear results
        for w in self.results_frame.winfo_children():
            w.destroy()
        
        # Show loading
        loading = ctk.CTkLabel(
            self.results_frame, text="Loading your playlists...",
            font=ctk.CTkFont(size=16), text_color=COLORS["subtext"]
        )
        loading.pack(pady=100)
        
        def load_thread():
            try:
                # Get logged in user and their playlists
                user = self.session.user
                
                # Try to get all playlists (including favorites)
                all_playlists = []
                try:
                    # Get user's own playlists
                    own_playlists = list(user.playlists())
                    all_playlists.extend(own_playlists)
                except Exception as e:
                    logger.warning(f"Could not load own playlists: {e}")
                
                try:
                    # Get favorite playlists too
                    fav_playlists = list(user.playlist_and_favorite_playlists())
                    # Add any that aren't already in the list
                    existing_ids = {getattr(p, 'id', None) for p in all_playlists}
                    for p in fav_playlists:
                        if getattr(p, 'id', None) not in existing_ids:
                            all_playlists.append(p)
                except Exception as e:
                    logger.warning(f"Could not load favorite playlists: {e}")
                
                # Create a pseudo SearchResult with only playlists
                results = SearchResult(
                    tracks=[],
                    albums=[],
                    artists=[],
                    playlists=all_playlists,
                    videos=[]
                )
                self.search_results = results
                self.after(0, lambda: self._display_my_playlists(all_playlists))
            except Exception as e:
                logger.exception("Error loading playlists")
                self.after(0, lambda: self._show_error(f"Failed to load playlists: {e}"))
        
        threading.Thread(target=load_thread, daemon=True).start()
    
    def _display_my_playlists(self, playlists):
        """Display user's personal playlists"""
        for w in self.results_frame.winfo_children():
            w.destroy()
        
        if not playlists:
            ctk.CTkLabel(
                self.results_frame, text="No playlists found",
                font=ctk.CTkFont(size=16), text_color=COLORS["subtext"]
            ).pack(pady=100)
            return
        
        # Header
        ctk.CTkLabel(
            self.results_frame, text=f"My Playlists ({len(playlists)})",
            font=ctk.CTkFont(family=FONT_FAMILY, size=18, weight="bold"),
            text_color=COLORS["text"]
        ).pack(anchor="w", pady=(0, 15))
        
        # Separate by public/private
        public_playlists = [p for p in playlists if getattr(p, 'public', False)]
        private_playlists = [p for p in playlists if not getattr(p, 'public', False)]
        
        # Display private playlists first (user's own)
        if private_playlists:
            ctk.CTkLabel(
                self.results_frame, text=f"Private ({len(private_playlists)})",
                font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                text_color=COLORS["subtext"]
            ).pack(anchor="w", pady=(5, 3))
            for playlist in private_playlists:
                self._create_playlist_row(playlist, is_public=False)
        
        # Display public/favorited playlists
        if public_playlists:
            ctk.CTkLabel(
                self.results_frame, text=f"Public/Favorited ({len(public_playlists)})",
                font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                text_color=COLORS["subtext"]
            ).pack(anchor="w", pady=(15, 3))
            for playlist in public_playlists:
                self._create_playlist_row(playlist, is_public=True)
    
    def _display_results(self, results):
        """Display search results with pagination"""
        for w in self.results_frame.winfo_children():
            w.destroy()
        
        if not results.albums and not results.tracks and not results.playlists:
            ctk.CTkLabel(
                self.results_frame, text="No results found",
                font=ctk.CTkFont(size=16), text_color=COLORS["subtext"]
            ).pack(pady=100)
            return
        
        # Albums section
        if results.albums:
            self._display_albums_section(results.albums)
        
        # Playlists section
        if results.playlists:
            self._display_playlists_section(results.playlists)
        
        # Tracks section
        if results.tracks:
            self._display_tracks_section(results.tracks)
    
    def _display_albums_section(self, albums):
        """Display albums with pagination"""
        total = len(albums)
        start = self.albums_page * self.ALBUMS_PER_PAGE
        end = min(start + self.ALBUMS_PER_PAGE, total)
        page_albums = albums[start:end]
        total_pages = (total + self.ALBUMS_PER_PAGE - 1) // self.ALBUMS_PER_PAGE
        
        # Header with pagination
        header = ctk.CTkFrame(self.results_frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 10))
        
        # Show "+" if more results available from API
        count_text = f"Albums ({total}+)" if self.albums_has_more else f"Albums ({total})"
        ctk.CTkLabel(
            header, text=count_text,
            font=ctk.CTkFont(family=FONT_FAMILY, size=18, weight="bold"),
            text_color=COLORS["text"]
        ).pack(side="left")
        
        # Show pagination if there are multiple pages OR more can be loaded
        if total_pages > 1 or self.albums_has_more:
            nav = ctk.CTkFrame(header, fg_color="transparent")
            nav.pack(side="right")
            
            ctk.CTkButton(
                nav, text="<", width=30, height=28,
                fg_color=COLORS["bg_light"], hover_color=COLORS["accent"],
                command=lambda: self._change_albums_page(-1),
                state="normal" if self.albums_page > 0 else "disabled"
            ).pack(side="left", padx=2)
            
            # Page indicator (show ? for unknown total when more available)
            page_text = f"{self.albums_page + 1}/?" if self.albums_has_more else f"{self.albums_page + 1}/{total_pages}"
            ctk.CTkLabel(
                nav, text=page_text,
                font=ctk.CTkFont(size=11), text_color=COLORS["subtext"]
            ).pack(side="left", padx=8)
            
            # Enable next button if on last page but more can be fetched
            can_go_next = self.albums_page < total_pages - 1 or self.albums_has_more
            ctk.CTkButton(
                nav, text=">", width=30, height=28,
                fg_color=COLORS["bg_light"], hover_color=COLORS["accent"],
                command=lambda: self._change_albums_page(1),
                state="normal" if can_go_next else "disabled"
            ).pack(side="left", padx=2)
        
        # Responsive album grid
        albums_grid = ctk.CTkFrame(self.results_frame, fg_color="transparent")
        albums_grid.pack(fill="x", pady=(0, 25))
        
        # Configure grid columns for flexibility
        for i in range(4):
            albums_grid.grid_columnconfigure(i, weight=1, uniform="album")
        
        for i, album in enumerate(page_albums):
            col = i % 4
            row = i // 4
            self._create_album_card(albums_grid, album, row, col)
    
    def _display_playlists_section(self, playlists):
        """Display playlists split into Public and Private with pagination"""
        # Separate public and private playlists
        public_playlists = [p for p in playlists if getattr(p, 'public', True)]
        private_playlists = [p for p in playlists if not getattr(p, 'public', True)]
        
        total = len(playlists)
        start = self.playlists_page * self.PLAYLISTS_PER_PAGE
        end = min(start + self.PLAYLISTS_PER_PAGE, total)
        total_pages = (total + self.PLAYLISTS_PER_PAGE - 1) // self.PLAYLISTS_PER_PAGE
        
        # Header with pagination
        header = ctk.CTkFrame(self.results_frame, fg_color="transparent")
        header.pack(fill="x", pady=(15, 10))
        
        count_text = f"Playlists ({total}+)" if self.playlists_has_more else f"Playlists ({total})"
        ctk.CTkLabel(
            header, text=count_text,
            font=ctk.CTkFont(family=FONT_FAMILY, size=18, weight="bold"),
            text_color=COLORS["text"]
        ).pack(side="left")
        
        if total_pages > 1 or self.playlists_has_more:
            nav = ctk.CTkFrame(header, fg_color="transparent")
            nav.pack(side="right")
            
            ctk.CTkButton(
                nav, text="<", width=30, height=28,
                fg_color=COLORS["bg_light"], hover_color=COLORS["accent"],
                command=lambda: self._change_playlists_page(-1),
                state="normal" if self.playlists_page > 0 else "disabled"
            ).pack(side="left", padx=2)
            
            page_text = f"{self.playlists_page + 1}/?" if self.playlists_has_more else f"{self.playlists_page + 1}/{total_pages}"
            ctk.CTkLabel(
                nav, text=page_text,
                font=ctk.CTkFont(size=11), text_color=COLORS["subtext"]
            ).pack(side="left", padx=8)
            
            can_go_next = self.playlists_page < total_pages - 1 or self.playlists_has_more
            ctk.CTkButton(
                nav, text=">", width=30, height=28,
                fg_color=COLORS["bg_light"], hover_color=COLORS["accent"],
                command=lambda: self._change_playlists_page(1),
                state="normal" if can_go_next else "disabled"
            ).pack(side="left", padx=2)
        
        # Show playlists for current page
        page_playlists = playlists[start:end]
        
        # Group page playlists by public/private
        page_public = [p for p in page_playlists if getattr(p, 'public', True)]
        page_private = [p for p in page_playlists if not getattr(p, 'public', True)]
        
        # Display public playlists
        if page_public:
            ctk.CTkLabel(
                self.results_frame, text="Public Playlists",
                font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                text_color=COLORS["subtext"]
            ).pack(anchor="w", pady=(5, 3))
            for playlist in page_public:
                self._create_playlist_row(playlist, is_public=True)
        
        # Display private playlists
        if page_private:
            ctk.CTkLabel(
                self.results_frame, text="Private Playlists",
                font=ctk.CTkFont(family=FONT_FAMILY, size=12),
                text_color=COLORS["subtext"]
            ).pack(anchor="w", pady=(10, 3))
            for playlist in page_private:
                self._create_playlist_row(playlist, is_public=False)
    
    def _display_tracks_section(self, tracks):
        """Display tracks with pagination"""
        total = len(tracks)
        start = self.tracks_page * self.TRACKS_PER_PAGE
        end = min(start + self.TRACKS_PER_PAGE, total)
        page_tracks = tracks[start:end]
        total_pages = (total + self.TRACKS_PER_PAGE - 1) // self.TRACKS_PER_PAGE
        
        # Header with pagination
        header = ctk.CTkFrame(self.results_frame, fg_color="transparent")
        header.pack(fill="x", pady=(15, 10))
        
        count_text = f"Tracks ({total}+)" if self.tracks_has_more else f"Tracks ({total})"
        ctk.CTkLabel(
            header, text=count_text,
            font=ctk.CTkFont(family=FONT_FAMILY, size=18, weight="bold"),
            text_color=COLORS["text"]
        ).pack(side="left")
        
        if total_pages > 1 or self.tracks_has_more:
            nav = ctk.CTkFrame(header, fg_color="transparent")
            nav.pack(side="right")
            
            ctk.CTkButton(
                nav, text="<", width=30, height=28,
                fg_color=COLORS["bg_light"], hover_color=COLORS["accent"],
                command=lambda: self._change_tracks_page(-1),
                state="normal" if self.tracks_page > 0 else "disabled"
            ).pack(side="left", padx=2)
            
            page_text = f"{self.tracks_page + 1}/?" if self.tracks_has_more else f"{self.tracks_page + 1}/{total_pages}"
            ctk.CTkLabel(
                nav, text=page_text,
                font=ctk.CTkFont(size=11), text_color=COLORS["subtext"]
            ).pack(side="left", padx=8)
            
            can_go_next = self.tracks_page < total_pages - 1 or self.tracks_has_more
            ctk.CTkButton(
                nav, text=">", width=30, height=28,
                fg_color=COLORS["bg_light"], hover_color=COLORS["accent"],
                command=lambda: self._change_tracks_page(1),
                state="normal" if can_go_next else "disabled"
            ).pack(side="left", padx=2)
        
        # Track rows
        for i, track in enumerate(page_tracks):
            self._create_track_row(self.results_frame, track, start + i + 1)
    
    def _change_albums_page(self, delta):
        """Change albums page and fetch more if needed"""
        new_page = self.albums_page + delta
        needed_items = (new_page + 1) * self.ALBUMS_PER_PAGE
        
        # Check if we need to fetch more from API
        if needed_items > len(self.search_results.albums) and self.albums_has_more:
            self._fetch_more_albums(new_page)
        else:
            self.albums_page = new_page
            if self.search_results:
                self._display_results(self.search_results)
    
    def _fetch_more_albums(self, target_page):
        """Fetch more albums from API"""
        def fetch_thread():
            try:
                offset = len(self.search_results.albums)
                more = search(self.session, self.search_query, SearchType.ALBUM, 
                             limit=self.API_FETCH_LIMIT, offset=offset)
                if len(more.albums) < self.API_FETCH_LIMIT:
                    self.albums_has_more = False
                # Append to existing results
                self.search_results.albums.extend(more.albums)
                self.albums_page = target_page
                self.after(0, lambda: self._display_results(self.search_results))
            except Exception as e:
                logger.exception("Fetch more albums error")
        threading.Thread(target=fetch_thread, daemon=True).start()
    
    def _change_playlists_page(self, delta):
        """Change playlists page and fetch more if needed"""
        new_page = self.playlists_page + delta
        needed_items = (new_page + 1) * self.PLAYLISTS_PER_PAGE
        
        if needed_items > len(self.search_results.playlists) and self.playlists_has_more:
            self._fetch_more_playlists(new_page)
        else:
            self.playlists_page = new_page
            if self.search_results:
                self._display_results(self.search_results)
    
    def _fetch_more_playlists(self, target_page):
        """Fetch more playlists from API"""
        def fetch_thread():
            try:
                offset = len(self.search_results.playlists)
                more = search(self.session, self.search_query, SearchType.PLAYLIST,
                             limit=self.API_FETCH_LIMIT, offset=offset)
                if len(more.playlists) < self.API_FETCH_LIMIT:
                    self.playlists_has_more = False
                self.search_results.playlists.extend(more.playlists)
                self.playlists_page = target_page
                self.after(0, lambda: self._display_results(self.search_results))
            except Exception as e:
                logger.exception("Fetch more playlists error")
        threading.Thread(target=fetch_thread, daemon=True).start()
    
    def _change_tracks_page(self, delta):
        """Change tracks page and fetch more if needed"""
        new_page = self.tracks_page + delta
        needed_items = (new_page + 1) * self.TRACKS_PER_PAGE
        
        if needed_items > len(self.search_results.tracks) and self.tracks_has_more:
            self._fetch_more_tracks(new_page)
        else:
            self.tracks_page = new_page
            if self.search_results:
                self._display_results(self.search_results)
    
    def _fetch_more_tracks(self, target_page):
        """Fetch more tracks from API"""
        def fetch_thread():
            try:
                offset = len(self.search_results.tracks)
                more = search(self.session, self.search_query, SearchType.TRACK,
                             limit=self.API_FETCH_LIMIT, offset=offset)
                if len(more.tracks) < self.API_FETCH_LIMIT:
                    self.tracks_has_more = False
                self.search_results.tracks.extend(more.tracks)
                self.tracks_page = target_page
                self.after(0, lambda: self._display_results(self.search_results))
            except Exception as e:
                logger.exception("Fetch more tracks error")
        threading.Thread(target=fetch_thread, daemon=True).start()
    
    def _create_playlist_row(self, playlist, is_public=True):
        """Create a playlist row with download options"""
        row = ctk.CTkFrame(self.results_frame, fg_color=COLORS["bg_medium"], corner_radius=8, height=70)
        row.pack(fill="x", pady=3)
        row.pack_propagate(False)
        
        # Playlist icon
        icon_label = ctk.CTkLabel(
            row, text="", width=55, height=55,
            fg_color=COLORS["bg_light"], corner_radius=6
        )
        icon_label.pack(side="left", padx=(10, 10), pady=7)
        
        # Load playlist image with caching (try multiple image methods)
        def get_playlist_url():
            try:
                if hasattr(playlist, 'image') and callable(playlist.image):
                    try:
                        return playlist.image(320)
                    except:
                        pass
                if hasattr(playlist, 'square_picture'):
                    try:
                        return playlist.square_picture(320)
                    except:
                        pass
                if hasattr(playlist, 'picture'):
                    try:
                        return playlist.picture(320)
                    except:
                        pass
            except:
                pass
            return None
        
        url = get_playlist_url()
        if url:
            playlist_id = getattr(playlist, 'id', None) or getattr(playlist, 'uuid', 'unknown')
            self._load_image_async(
                url, (55, 55),
                lambda img: icon_label.configure(image=img),
                cache_key=f"playlist_{playlist_id}_55"
            )
        
        # Info
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=5, pady=8)
        
        # Playlist name with public/private badge
        name_frame = ctk.CTkFrame(info, fg_color="transparent")
        name_frame.pack(anchor="w")
        
        name = playlist.name[:35] + "..." if len(playlist.name) > 35 else playlist.name
        ctk.CTkLabel(
            name_frame, text=name,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=COLORS["text"]
        ).pack(side="left")
        
        # Public/Private badge
        badge_text = "Public" if is_public else "Private"
        badge_color = COLORS["green"] if is_public else COLORS["subtext"]
        ctk.CTkLabel(
            name_frame, text=f"  [{badge_text}]",
            font=ctk.CTkFont(family=FONT_FAMILY, size=9),
            text_color=badge_color
        ).pack(side="left")
        
        creator = playlist.creator.name if playlist.creator else "Tidal"
        tracks_count = playlist.num_tracks if playlist.num_tracks else "?"
        ctk.CTkLabel(
            info, text=f"by {creator}  •  {tracks_count} tracks",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color=COLORS["subtext"], anchor="w"
        ).pack(anchor="w")
        
        # Download buttons
        btn_frame = ctk.CTkFrame(row, fg_color="transparent")
        btn_frame.pack(side="right", padx=10, pady=8)
        
        # Download as one folder (playlist name)
        ctk.CTkButton(
            btn_frame, text="As One", width=70, height=30,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["bg_dark"],
            font=ctk.CTkFont(size=11),
            command=lambda p=playlist: self._download_playlist(p, as_album=True)
        ).pack(side="left", padx=3)
        
        # Download separately (by original artist/album)
        ctk.CTkButton(
            btn_frame, text="Separate", width=70, height=30,
            fg_color=COLORS["bg_light"], hover_color=COLORS["accent"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=11),
            command=lambda p=playlist: self._download_playlist(p, as_album=False)
        ).pack(side="left", padx=3)
    
    def _create_album_card(self, parent, album, row, col):
        """Create an album card"""
        card = ctk.CTkFrame(parent, fg_color=COLORS["bg_medium"], corner_radius=12, width=200)
        card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
        
        # Placeholder art
        art = ctk.CTkLabel(
            card, text="", width=160, height=160,
            fg_color=COLORS["bg_light"], corner_radius=8,
            font=ctk.CTkFont(size=48)
        )
        art.pack(padx=15, pady=(15, 10))
        
        # Load art async with caching
        url = album.image(320) if hasattr(album, 'image') else None
        if url:
            self._load_image_async(
                url, (160, 160),
                lambda img: art.configure(image=img, text=""),
                cache_key=f"album_{album.id}_160"
            )
        
        # Title
        title = album.name[:22] + "..." if len(album.name) > 22 else album.name
        ctk.CTkLabel(
            card, text=title,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text"], wraplength=170
        ).pack(padx=10, pady=(5, 2))
        
        # Artist
        artist = album.artist.name if album.artist else "Unknown"
        artist = artist[:20] + "..." if len(artist) > 20 else artist
        ctk.CTkLabel(
            card, text=artist,
            font=ctk.CTkFont(size=11),
            text_color=COLORS["subtext"]
        ).pack(padx=10, pady=(0, 5))
        
        # Download button
        ctk.CTkButton(
            card, text="Download", height=30,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["bg_dark"],
            command=lambda a=album: self._download_album(a)
        ).pack(fill="x", padx=15, pady=(5, 15))
    
    def _create_track_row(self, parent, track, num):
        """Create a track row with artist, album, and thumbnail"""
        row = ctk.CTkFrame(parent, fg_color=COLORS["bg_medium"], corner_radius=8, height=60)
        row.pack(fill="x", pady=3)
        row.pack_propagate(False)
        
        # Album thumbnail placeholder
        thumb_label = ctk.CTkLabel(
            row, text="", width=50, height=50,
            fg_color=COLORS["bg_light"], corner_radius=6
        )
        thumb_label.pack(side="left", padx=(10, 10), pady=5)
        
        # Load album art async with caching
        album = getattr(track, 'album', None)
        if album:
            url = album.image(160) if hasattr(album, 'image') else None
            if url:
                self._load_image_async(
                    url, (50, 50),
                    lambda img: thumb_label.configure(image=img),
                    cache_key=f"album_{getattr(album, 'id', 'unknown')}_50"
                )
        
        # Info section
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        
        # Track number + Title
        title_row = ctk.CTkFrame(info, fg_color="transparent")
        title_row.pack(fill="x")
        
        ctk.CTkLabel(
            title_row, text=str(num).zfill(2), width=25,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11), text_color=COLORS["subtext"]
        ).pack(side="left")
        
        title = track.name[:40] + "..." if len(track.name) > 40 else track.name
        ctk.CTkLabel(
            title_row, text=title,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"), 
            text_color=COLORS["text"], anchor="w"
        ).pack(side="left", padx=(5, 0))
        
        # Artist + Album row
        meta_row = ctk.CTkFrame(info, fg_color="transparent")
        meta_row.pack(fill="x", pady=(2, 0))
        
        artist_name = track.artist.name if track.artist else "Unknown Artist"
        artist_name = artist_name[:25] + "..." if len(artist_name) > 25 else artist_name
        
        album_name = album.name if album else "Unknown Album"
        album_name = album_name[:25] + "..." if len(album_name) > 25 else album_name
        
        ctk.CTkLabel(
            meta_row, text=f"{artist_name}  •  {album_name}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10), 
            text_color=COLORS["subtext"], anchor="w"
        ).pack(side="left")
        
        # Right side: Duration + Download button
        right_frame = ctk.CTkFrame(row, fg_color="transparent")
        right_frame.pack(side="right", padx=10, pady=5)
        
        # Duration
        dur = f"{track.duration // 60}:{track.duration % 60:02d}" if track.duration else "--:--"
        ctk.CTkLabel(
            right_frame, text=dur, width=45,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10), text_color=COLORS["subtext"]
        ).pack(side="left", padx=(0, 10))
        
        # Download button
        ctk.CTkButton(
            right_frame, text="+", width=35, height=30,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            text_color=COLORS["bg_dark"],
            font=ctk.CTkFont(size=14, weight="bold"),
            command=lambda t=track: self._download_track(t)
        ).pack(side="right")
    
    def _download_album(self, album):
        """Download album"""
        if not self.download_queue:
            self._show_toast("Not connected", COLORS["red"])
            return
        
        def dl_thread():
            try:
                tasks = create_album_tasks(self.config, self.session, album)
                self.download_queue.add_tasks(tasks)
                self.after(0, lambda: self._on_tasks_added(tasks))
            except Exception as e:
                self.after(0, lambda: self._show_toast(f"Error: {e}", COLORS["red"]))
        
        threading.Thread(target=dl_thread, daemon=True).start()
    
    def _download_track(self, track):
        """Download track"""
        if not self.download_queue:
            self._show_toast("Not connected", COLORS["red"])
            return
        
        task = create_track_task(self.config, track)
        self.download_queue.add_task(task)
        self._on_tasks_added([task])
    
    def _download_playlist(self, playlist, as_album=True):
        """Download playlist with option for folder organization"""
        if not self.download_queue:
            self._show_toast("Not connected", COLORS["red"])
            return
        
        def dl_thread():
            try:
                from src.downloader import create_playlist_tasks
                
                if as_album:
                    # Download as "Various Artists - PlaylistName" album
                    tasks = create_playlist_tasks(
                        self.config, self.session, playlist, 
                        as_compilation=True
                    )
                    msg = f"Added {len(tasks)} tracks as compilation"
                else:
                    # Download split by original artist/album
                    tasks = create_playlist_tasks(
                        self.config, self.session, playlist,
                        as_compilation=False
                    )
                    msg = f"Added {len(tasks)} tracks by artist"
                
                self.download_queue.add_tasks(tasks)
                self.after(0, lambda: self._on_tasks_added_msg(tasks, msg))
            except Exception as e:
                logger.exception("Playlist download error")
                self.after(0, lambda: self._show_toast(f"Error: {e}", COLORS["red"]))
        
        threading.Thread(target=dl_thread, daemon=True).start()
    
    def _on_tasks_added_msg(self, tasks, msg):
        """Called when tasks are added with custom message"""
        self._show_toast(msg, COLORS["green"])
        self._refresh_downloads_ui()
        if self.download_queue and not self.download_queue.is_running:
            self._start_downloads()
    
    def _on_tasks_added(self, tasks):
        """Called when tasks are added to the queue"""
        self._show_toast(f"Added {len(tasks)} to queue", COLORS["green"])
        self._refresh_downloads_ui()
        # Auto-start downloads if not already running
        if self.download_queue and not self.download_queue.is_running:
            self._start_downloads()
    
    def _refresh_downloads_ui(self):
        """Refresh the downloads list UI with incremental updates to prevent flashing"""
        if not self.download_queue:
            return
        
        # Get all tasks and deduplicate by ID (same task can be in queue and completed)
        all_tasks_dict = {}
        for task in self.download_queue.queue:
            all_tasks_dict[task.id] = task
        for task in self.download_queue.completed:
            all_tasks_dict[task.id] = task  # Completed takes precedence
        for task in self.download_queue.failed:
            all_tasks_dict[task.id] = task  # Failed takes precedence
        
        current_task_ids = set(all_tasks_dict.keys())
        
        # Check if we need a full rebuild (tasks added/removed or first load)
        needs_rebuild = (
            current_task_ids != self._last_task_ids or
            not self.downloads_list.winfo_children()
        )
        
        if needs_rebuild:
            # Full rebuild only when structure changes
            self._full_rebuild_downloads(all_tasks_dict)
            self._last_task_ids = current_task_ids.copy()
        else:
            # Incremental update - just update status/progress
            self._incremental_update_downloads(all_tasks_dict)
        
        # Update stats
        self._update_stats()
    
    def _full_rebuild_downloads(self, all_tasks_dict):
        """Full rebuild of downloads UI (only called when tasks are added/removed)"""
        # Clear current list and widget tracking
        for w in self.downloads_list.winfo_children():
            w.destroy()
        self._download_widgets.clear()
        self._album_widgets.clear()
        
        all_tasks = list(all_tasks_dict.values())
        
        if not all_tasks:
            ctk.CTkLabel(
                self.downloads_list,
                text="No downloads yet\nSearch and add music to queue",
                font=ctk.CTkFont(size=14),
                text_color=COLORS["subtext"]
            ).pack(pady=80)
            return
        
        # Group tasks: first by playlist (for compilations), then by album
        playlists = {}  # playlist_name -> tasks
        albums = {}     # album_id -> {"album": album, "tasks": []}
        singles = []
        
        for task in all_tasks:
            # Check if this is a playlist compilation download
            if task.playlist_name:
                if task.playlist_name not in playlists:
                    playlists[task.playlist_name] = []
                playlists[task.playlist_name].append(task)
            elif task.album:
                album_id = task.album.id
                if album_id not in albums:
                    albums[album_id] = {"album": task.album, "tasks": []}
                albums[album_id]["tasks"].append(task)
            else:
                # Treat as single - use track name as "album"
                track_album = getattr(task.item, 'album', None)
                if track_album:
                    album_id = track_album.id
                    if album_id not in albums:
                        albums[album_id] = {"album": track_album, "tasks": []}
                    albums[album_id]["tasks"].append(task)
                else:
                    singles.append(task)
        
        # Show playlists first (as they are usually the current download)
        for playlist_name, tasks in playlists.items():
            self._create_playlist_group(playlist_name, tasks)
        
        # Show albums
        for album_id, data in albums.items():
            self._create_album_group(data["album"], data["tasks"])
        
        # Show singles (if any without album)
        if singles:
            self._create_singles_group(singles)
    
    def _incremental_update_downloads(self, all_tasks_dict):
        """Update only the dynamic parts of download widgets (status, progress)"""
        status_colors = {
            DownloadStatus.QUEUED: COLORS["subtext"],
            DownloadStatus.DOWNLOADING: COLORS["blue"],
            DownloadStatus.COMPLETED: COLORS["green"],
            DownloadStatus.FAILED: COLORS["red"],
            DownloadStatus.SKIPPED: COLORS["yellow"],
        }
        
        # Update individual track widgets
        for task_id, widgets in self._download_widgets.items():
            task = all_tasks_dict.get(task_id)
            if not task:
                continue
            
            # Update icon
            if 'icon_label' in widgets:
                if task.is_converting:
                    icon_text, icon_color = "~", COLORS["yellow"]
                elif task.status == DownloadStatus.COMPLETED:
                    icon_text, icon_color = "•", COLORS["green"]
                elif task.status == DownloadStatus.FAILED:
                    icon_text, icon_color = "×", COLORS["red"]
                elif task.status == DownloadStatus.DOWNLOADING:
                    icon_text, icon_color = "•", COLORS["blue"]
                else:
                    icon_text, icon_color = "○", COLORS["subtext"]
                widgets['icon_label'].configure(text=icon_text, text_color=icon_color)
            
            # Update status text
            if 'status_label' in widgets:
                if task.is_converting:
                    status_text = "Converting to FLAC..."
                    status_color = COLORS["yellow"]
                elif task.status == DownloadStatus.DOWNLOADING:
                    status_text = f"Downloading {task.progress:.0f}%"
                    status_color = COLORS["blue"]
                else:
                    status_text = task.status.value.capitalize()
                    status_color = status_colors.get(task.status, COLORS["subtext"])
                widgets['status_label'].configure(text=status_text, text_color=status_color)
            
            # Update progress bar
            if 'progress_bar' in widgets and widgets['progress_bar']:
                if task.status == DownloadStatus.DOWNLOADING and not task.is_converting:
                    widgets['progress_bar'].configure(progress_color=COLORS["blue"])
                    widgets['progress_bar'].set(task.progress / 100)
                elif task.is_converting:
                    widgets['progress_bar'].configure(progress_color=COLORS["yellow"])
                    widgets['progress_bar'].set(0.5)
                else:
                    widgets['progress_bar'].set(0)
        
        # Update album group widgets
        for album_id, widgets in self._album_widgets.items():
            # Check if this is a playlist group
            if album_id.startswith("playlist_"):
                # Find tasks for this playlist
                playlist_name = album_id[9:]  # Remove "playlist_" prefix
                album_tasks = [t for t in all_tasks_dict.values() if t.playlist_name == playlist_name]
            else:
                # Find tasks for this album
                album_tasks = [t for t in all_tasks_dict.values() 
                              if (t.album and t.album.id == album_id) or 
                                 (getattr(t.item, 'album', None) and getattr(t.item, 'album').id == album_id)]
            
            if not album_tasks:
                continue
            
            completed = sum(1 for t in album_tasks if t.status == DownloadStatus.COMPLETED)
            total = len(album_tasks)
            
            # Update progress label
            if 'progress_label' in widgets:
                progress_color = COLORS["green"] if completed == total else COLORS["blue"] if completed > 0 else COLORS["subtext"]
                widgets['progress_label'].configure(text=f"{completed}/{total}", text_color=progress_color)
            
            # Update progress bar
            if 'progress_bar' in widgets and total > 0:
                widgets['progress_bar'].set(completed / total)
        
        # Update stats
        self._update_stats()
    
    def _create_album_group(self, album, tasks):
        """Create an album group widget with collapsible tracks"""
        album_id = album.id
        
        # Default to collapsed for new albums
        if album_id not in self.expanded_albums:
            self.expanded_albums[album_id] = False
        
        is_expanded = self.expanded_albums[album_id]
        
        # Calculate album stats
        completed = sum(1 for t in tasks if t.status == DownloadStatus.COMPLETED)
        failed = sum(1 for t in tasks if t.status == DownloadStatus.FAILED)
        total = len(tasks)
        
        # Album header (clickable)
        header = ctk.CTkFrame(self.downloads_list, fg_color=COLORS["bg_light"], corner_radius=8)
        header.pack(fill="x", pady=(10, 2))
        
        # Album info row
        info_row = ctk.CTkFrame(header, fg_color="transparent")
        info_row.pack(fill="x", padx=10, pady=8)
        
        # Expand/Collapse arrow
        arrow_text = "−" if is_expanded else "+"
        arrow_btn = ctk.CTkButton(
            info_row, text=arrow_text, width=25, height=25,
            fg_color="transparent", hover_color=COLORS["bg_medium"],
            text_color=COLORS["subtext"],
            font=ctk.CTkFont(size=12),
            command=lambda: self._toggle_album(album_id)
        )
        arrow_btn.pack(side="left", padx=(0, 5))
        
        # Album thumbnail placeholder
        thumb_label = ctk.CTkLabel(
            info_row, text="", width=45, height=45,
            fg_color=COLORS["bg_medium"], corner_radius=6,
            font=ctk.CTkFont(size=20)
        )
        thumb_label.pack(side="left", padx=(0, 10))
        
        # Load album art async with caching
        url = album.image(160) if hasattr(album, 'image') else None
        if url:
            self._load_image_async(
                url, (45, 45),
                lambda img: thumb_label.configure(image=img, text=""),
                cache_key=f"album_{album.id}_45"
            )
        
        # Album name with artist (also clickable to toggle)
        artist_name = album.artist.name if album.artist else "Unknown Artist"
        album_title = album.name if album.name else "Unknown Album"
        full_name = f"{artist_name} - {album_title}"
        # Truncate if too long
        display_name = full_name[:40] + "..." if len(full_name) > 40 else full_name
        name_label = ctk.CTkLabel(
            info_row, text=display_name,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text"]
        )
        name_label.pack(side="left", padx=(0, 10))
        name_label.bind("<Button-1>", lambda e: self._toggle_album(album_id))
        
        # Progress indicator
        progress_text = f"{completed}/{total}"
        progress_color = COLORS["green"] if completed == total else COLORS["blue"] if completed > 0 else COLORS["subtext"]
        progress_label = ctk.CTkLabel(
            info_row, text=progress_text,
            font=ctk.CTkFont(size=11),
            text_color=progress_color
        )
        progress_label.pack(side="right", padx=5)
        
        # Album progress bar
        progress_bar = None
        if total > 0:
            progress_bar = ctk.CTkProgressBar(header, height=3, progress_color=COLORS["accent"], fg_color=COLORS["bg_medium"])
            progress_bar.pack(fill="x", padx=12, pady=(0, 8))
            progress_bar.set(completed / total)
        
        # Store widget references for incremental updates
        self._album_widgets[album_id] = {
            'header': header,
            'progress_label': progress_label,
            'progress_bar': progress_bar,
            'thumb_label': thumb_label
        }
        
        # Track rows (only if expanded)
        if is_expanded:
            for task in tasks:
                self._create_track_download_item(task, indent=True)
    
    def _create_playlist_group(self, playlist_name, tasks):
        """Create a playlist group widget with collapsible tracks for playlist compilation downloads"""
        # Use playlist_name as a unique identifier (prefixed to avoid collision with album IDs)
        playlist_id = f"playlist_{playlist_name}"
        
        # Default to collapsed for new playlists
        if playlist_id not in self.expanded_albums:
            self.expanded_albums[playlist_id] = False
        
        is_expanded = self.expanded_albums[playlist_id]
        
        # Calculate playlist stats
        completed = sum(1 for t in tasks if t.status == DownloadStatus.COMPLETED)
        failed = sum(1 for t in tasks if t.status == DownloadStatus.FAILED)
        total = len(tasks)
        
        # Get album artist from first task
        album_artist = tasks[0].playlist_album_artist if tasks else "Various Artists"
        
        # Playlist header (clickable) - uses different color to distinguish from albums
        header = ctk.CTkFrame(self.downloads_list, fg_color="#3d2f5c", corner_radius=8)  # Purple tint for playlists
        header.pack(fill="x", pady=(10, 2))
        
        # Playlist info row
        info_row = ctk.CTkFrame(header, fg_color="transparent")
        info_row.pack(fill="x", padx=10, pady=8)
        
        # Expand/Collapse arrow
        arrow_text = "−" if is_expanded else "+"
        arrow_btn = ctk.CTkButton(
            info_row, text=arrow_text, width=25, height=25,
            fg_color="transparent", hover_color=COLORS["bg_medium"],
            text_color=COLORS["subtext"],
            font=ctk.CTkFont(size=12),
            command=lambda: self._toggle_album(playlist_id)
        )
        arrow_btn.pack(side="left", padx=(0, 5))
        
        # Playlist icon (music note symbol instead of album art)
        icon_label = ctk.CTkLabel(
            info_row, text="📋", width=45, height=45,
            fg_color=COLORS["bg_medium"], corner_radius=6,
            font=ctk.CTkFont(size=20)
        )
        icon_label.pack(side="left", padx=(0, 10))
        
        # Playlist name with album artist
        full_name = f"{album_artist} - {playlist_name}"
        # Truncate if too long
        display_name = full_name[:45] + "..." if len(full_name) > 45 else full_name
        name_label = ctk.CTkLabel(
            info_row, text=display_name,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text"]
        )
        name_label.pack(side="left", padx=(0, 10))
        name_label.bind("<Button-1>", lambda e: self._toggle_album(playlist_id))
        
        # Playlist badge
        ctk.CTkLabel(
            info_row, text="Playlist",
            font=ctk.CTkFont(size=9),
            text_color="#a78bfa",  # Light purple
            fg_color="#4c3875",
            corner_radius=4,
            width=50, height=18
        ).pack(side="left", padx=5)
        
        # Progress indicator
        progress_text = f"{completed}/{total}"
        progress_color = COLORS["green"] if completed == total else COLORS["blue"] if completed > 0 else COLORS["subtext"]
        progress_label = ctk.CTkLabel(
            info_row, text=progress_text,
            font=ctk.CTkFont(size=11),
            text_color=progress_color
        )
        progress_label.pack(side="right", padx=5)
        
        # Playlist progress bar
        progress_bar = None
        if total > 0:
            progress_bar = ctk.CTkProgressBar(header, height=3, progress_color="#a78bfa", fg_color=COLORS["bg_medium"])  # Purple progress
            progress_bar.pack(fill="x", padx=12, pady=(0, 8))
            progress_bar.set(completed / total)
        
        # Store widget references for incremental updates
        self._album_widgets[playlist_id] = {
            'header': header,
            'progress_label': progress_label,
            'progress_bar': progress_bar,
            'thumb_label': icon_label
        }
        
        # Track rows (only if expanded)
        if is_expanded:
            for task in tasks:
                self._create_track_download_item(task, indent=True)
    
    def _toggle_album(self, album_id):
        """Toggle album expansion state"""
        self.expanded_albums[album_id] = not self.expanded_albums.get(album_id, False)
        # Force a full rebuild since visible widgets change
        self._last_task_ids = set()
        self._refresh_downloads_ui()
    
    def _create_singles_group(self, tasks):
        """Create a singles group"""
        header = ctk.CTkFrame(self.downloads_list, fg_color=COLORS["bg_light"], corner_radius=8)
        header.pack(fill="x", pady=(10, 2))
        
        ctk.CTkLabel(
            header, text="Singles",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text"]
        ).pack(padx=15, pady=10, anchor="w")
        
        for task in tasks:
            self._create_track_download_item(task, indent=True)
    
    def _create_track_download_item(self, task, indent=False):
        """Create a download item widget for a track"""
        status_colors = {
            DownloadStatus.QUEUED: COLORS["subtext"],
            DownloadStatus.DOWNLOADING: COLORS["blue"],
            DownloadStatus.COMPLETED: COLORS["green"],
            DownloadStatus.FAILED: COLORS["red"],
            DownloadStatus.SKIPPED: COLORS["yellow"],
        }
        
        frame = ctk.CTkFrame(self.downloads_list, fg_color=COLORS["bg_medium"], corner_radius=6, height=55)
        frame.pack(fill="x", pady=1, padx=(20 if indent else 0, 0))
        frame.pack_propagate(False)
        
        # Status icon (using simple dots/shapes)
        if task.is_converting:
            icon_text = "~"
            icon_color = COLORS["yellow"]
        elif task.status == DownloadStatus.COMPLETED:
            icon_text = "•"
            icon_color = COLORS["green"]
        elif task.status == DownloadStatus.FAILED:
            icon_text = "×"
            icon_color = COLORS["red"]
        elif task.status == DownloadStatus.DOWNLOADING:
            icon_text = "•"
            icon_color = COLORS["blue"]
        else:
            icon_text = "○"
            icon_color = COLORS["subtext"]
        
        icon_label = ctk.CTkLabel(
            frame, text=icon_text, width=25,
            font=ctk.CTkFont(size=14),
            text_color=icon_color
        )
        icon_label.pack(side="left", padx=(10, 5))
        
        # Info frame
        info = ctk.CTkFrame(frame, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=5, pady=6)
        
        # Title row
        title_row = ctk.CTkFrame(info, fg_color="transparent")
        title_row.pack(fill="x")
        
        # Track number + Title
        track_num = f"{task.track_number:02d}. " if task.track_number else ""
        title = task.item.name[:35] + "..." if len(task.item.name) > 35 else task.item.name
        ctk.CTkLabel(
            title_row, text=f"{track_num}{title}",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["text"], anchor="w"
        ).pack(side="left")
        
        # Format info (codec/quality)
        format_info = task.format_info
        if format_info:
            ctk.CTkLabel(
                title_row, text=format_info,
                font=ctk.CTkFont(size=9),
                text_color=COLORS["accent"], anchor="e"
            ).pack(side="right", padx=(10, 0))
        
        # Status row
        status_row = ctk.CTkFrame(info, fg_color="transparent")
        status_row.pack(fill="x", pady=(2, 0))
        
        # Status text
        if task.is_converting:
            status_text = "Converting to FLAC..."
            status_color = COLORS["yellow"]
        elif task.status == DownloadStatus.DOWNLOADING:
            status_text = f"Downloading {task.progress:.0f}%"
            status_color = COLORS["blue"]
        else:
            status_text = task.status.value.capitalize()
            status_color = status_colors.get(task.status, COLORS["subtext"])
        
        status_label = ctk.CTkLabel(
            status_row, text=status_text,
            font=ctk.CTkFont(size=9),
            text_color=status_color,
            anchor="w"
        )
        status_label.pack(side="left")
        
        # Progress bar container (always create, hide/show as needed)
        bar_frame = ctk.CTkFrame(status_row, fg_color="transparent")
        bar_frame.pack(side="right", padx=(10, 0))
        
        # Create progress bar - will be updated incrementally
        progress_bar = ctk.CTkProgressBar(bar_frame, width=120, height=4, progress_color=COLORS["blue"], fg_color=COLORS["bg_dark"])
        progress_bar.pack(side="left")
        
        # Set initial progress bar state
        if task.status == DownloadStatus.DOWNLOADING and not task.is_converting:
            progress_bar.set(task.progress / 100)
            progress_bar.configure(progress_color=COLORS["blue"])
        elif task.is_converting:
            progress_bar.set(0.5)
            progress_bar.configure(progress_color=COLORS["yellow"])
        else:
            # Hide progress bar for non-active states
            progress_bar.set(0)
        
        # Store widget references for incremental updates
        self._download_widgets[task.id] = {
            'frame': frame,
            'icon_label': icon_label,
            'status_label': status_label,
            'progress_bar': progress_bar,
            'bar_frame': bar_frame
        }
    
    def _update_stats(self):
        """Update download statistics"""
        if not self.download_queue:
            return
        
        status = self.download_queue.get_status()
        self.stat_queued.configure(text=str(status["queued"]))
        self.stat_active.configure(text=str(status["downloading"]))
        self.stat_done.configure(text=str(status["completed"]))
        self.stat_failed.configure(text=str(status["failed"]))
    
    def _start_downloads(self):
        """Start downloads"""
        if self.download_queue and not self.download_queue.is_running:
            self.download_queue.start_workers(None)
            self._show_toast("Downloads started", COLORS["green"])
            # Start periodic UI refresh
            self._start_download_refresh()
    
    def _start_download_refresh(self):
        """Start periodic refresh of download UI"""
        def refresh():
            if self.download_queue and self.download_queue.is_running:
                self._refresh_downloads_ui()
                self.after(800, refresh)  # Refresh every 800ms for better responsiveness
        refresh()
    
    def _stop_downloads(self):
        """Stop downloads"""
        if self.download_queue:
            self.download_queue.stop_workers()
            self._show_toast("Downloads stopped", COLORS["yellow"])
            self._refresh_downloads_ui()
    
    def _clear_downloads(self):
        """Clear downloads"""
        if self.download_queue:
            self.download_queue.clear()
            self._show_toast("Queue cleared", COLORS["green"])
            self._refresh_downloads_ui()
    
    def _save_settings(self):
        """Save settings to config and .env file"""
        try:
            from pathlib import Path
            from src.config import save_config
            import tidalapi
            
            # Read values from widgets
            quality_str = self.settings_widgets["download_quality"].get()
            quality_map = {
                "NORMAL": tidalapi.Quality.low_96k,
                "HIGH": tidalapi.Quality.low_320k,
                "LOSSLESS": tidalapi.Quality.high_lossless,
                "HI_RES": tidalapi.Quality.hi_res_lossless,
            }
            
            # Update config object
            self.config.download_quality = quality_map.get(quality_str, tidalapi.Quality.high_lossless)
            self.config.download_folder = Path(self.settings_widgets["download_folder"].get())
            
            try:
                self.config.max_concurrent_downloads = int(self.settings_widgets["max_concurrent"].get())
            except ValueError:
                self.config.max_concurrent_downloads = 3
            
            self.config.album_folder_template = self.settings_widgets["album_folder_template"].get()
            self.config.track_file_template = self.settings_widgets["track_file_template"].get()
            self.config.album_art_filename = self.settings_widgets["album_art_filename"].get()
            
            self.config.embed_album_art = bool(self.settings_widgets["embed_album_art"].get())
            self.config.save_album_art = bool(self.settings_widgets["save_album_art"].get())
            self.config.embed_lyrics = bool(self.settings_widgets["embed_lyrics"].get())
            self.config.skip_existing = bool(self.settings_widgets["skip_existing"].get())
            
            # Playlist settings
            self.config.playlist_album_artist = self.settings_widgets["playlist_album_artist"].get() or "Various Artists"
            
            # Save to .env file
            save_config(self.config, Path(".env"))
            
            self._show_toast("Settings saved!", COLORS["green"])
            logger.info("Settings saved successfully")
            
        except Exception as e:
            logger.exception("Error saving settings")
            self._show_toast(f"Error saving: {e}", COLORS["red"])
    
    def _show_toast(self, message, color):
        """Show toast notification"""
        toast = ctk.CTkFrame(self, fg_color=COLORS["bg_medium"], corner_radius=10)
        ctk.CTkLabel(toast, text=message, text_color=color, font=ctk.CTkFont(size=13)).pack(padx=20, pady=10)
        toast.place(relx=0.5, rely=0.92, anchor="center")
        self.after(2500, toast.destroy)
    
    def _show_error(self, message):
        """Show error message"""
        for w in self.results_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.results_frame, text=f"❌ {message}",
            font=ctk.CTkFont(size=14), text_color=COLORS["red"]
        ).pack(pady=100)


def main():
    """Main entry point"""
    logger.info("Starting Tidal MDL GUI")
    app = TidalMDLApp()
    
    def on_closing():
        """Cleanup on app close"""
        try:
            # Shutdown thread pool
            app._image_executor.shutdown(wait=False)
            # Clear image cache
            app._image_cache.clear()
            app._image_cache_order.clear()
        except:
            pass
        app.destroy()
    
    app.protocol("WM_DELETE_WINDOW", on_closing)
    app.mainloop()


if __name__ == "__main__":
    main()
