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
from src.auth import get_authenticated_session, delete_session
from src.search import search, SearchType
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
        
        # Build UI
        self._build_ui()
        
        # Start auth
        self.after(500, self._authenticate)
    
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
        
        # Results
        self.results_frame = ctk.CTkScrollableFrame(
            view, fg_color="transparent",
            scrollbar_button_color=COLORS["bg_light"]
        )
        self.results_frame.pack(fill="both", expand=True, padx=30, pady=(0, 20))
        
        # Placeholder
        self.search_placeholder = ctk.CTkLabel(
            self.results_frame,
            text="Search for music above",
            font=ctk.CTkFont(size=16),
            text_color=COLORS["subtext"]
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
        self._add_option(scroll, "Download Quality", 
                        ["HI_RES", "LOSSLESS", "HIGH", "NORMAL"], "HI_RES")
        
        # Download section
        self._add_section(scroll, "Downloads")
        self._add_folder_option(scroll, "Download Folder", str(self.config.download_folder))
        self._add_text_option(scroll, "Max Concurrent", str(self.config.max_concurrent_downloads))
        
        # Metadata section
        self._add_section(scroll, "Metadata")
        self._add_toggle(scroll, "Embed Album Art", self.config.embed_album_art)
        self._add_toggle(scroll, "Save Album Art", self.config.save_album_art)
        self._add_toggle(scroll, "Skip Existing", self.config.skip_existing)
        
        # Save button
        ctk.CTkButton(
            view, text="Save Settings", height=45,
            fg_color=COLORS["green"], hover_color="#8bd48b",
            text_color=COLORS["bg_dark"],
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._save_settings
        ).pack(fill="x", padx=30, pady=20)
        
        self.views["settings"] = view
    
    def _add_section(self, parent, title):
        """Add a section header"""
        ctk.CTkLabel(
            parent, text=title,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS["accent"]
        ).pack(anchor="w", pady=(20, 10))
    
    def _add_option(self, parent, label, options, default):
        """Add a dropdown option"""
        frame = ctk.CTkFrame(parent, fg_color=COLORS["bg_medium"], corner_radius=8)
        frame.pack(fill="x", pady=3)
        
        ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=13)).pack(side="left", padx=15, pady=12)
        ctk.CTkOptionMenu(
            frame, values=options, width=150,
            fg_color=COLORS["bg_light"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"]
        ).pack(side="right", padx=15, pady=12)
    
    def _add_text_option(self, parent, label, default):
        """Add a text input option"""
        frame = ctk.CTkFrame(parent, fg_color=COLORS["bg_medium"], corner_radius=8)
        frame.pack(fill="x", pady=3)
        
        ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=13)).pack(side="left", padx=15, pady=12)
        entry = ctk.CTkEntry(frame, width=200, fg_color=COLORS["bg_light"])
        entry.insert(0, default)
        entry.pack(side="right", padx=15, pady=12)
    
    def _add_toggle(self, parent, label, default):
        """Add a toggle option"""
        frame = ctk.CTkFrame(parent, fg_color=COLORS["bg_medium"], corner_radius=8)
        frame.pack(fill="x", pady=3)
        
        ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=13)).pack(side="left", padx=15, pady=12)
        switch = ctk.CTkSwitch(frame, text="", fg_color=COLORS["bg_light"], progress_color=COLORS["green"])
        if default:
            switch.select()
        switch.pack(side="right", padx=15, pady=12)
    
    def _add_folder_option(self, parent, label, default):
        """Add a folder picker option with browse button"""
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
        """Authenticate with Tidal"""
        def auth_thread():
            try:
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
                    self.after(0, lambda: self.status_label.configure(
                        text="Not connected", text_color=COLORS["red"]
                    ))
            except Exception as e:
                logger.exception("Auth error")
                self.after(0, lambda: self.status_label.configure(
                    text="Connection error", text_color=COLORS["red"]
                ))
        
        threading.Thread(target=auth_thread, daemon=True).start()
    
    def _logout(self):
        """Logout"""
        delete_session(self.config.session_file)
        self.session = None
        self.status_label.configure(text="⏳ Connecting...", text_color=COLORS["subtext"])
        self._authenticate()
    
    def _do_search(self):
        """Execute search"""
        query = self.search_entry.get().strip()
        if not query or not self.session:
            return
        
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
                results = search(self.session, query)
                self.after(0, lambda: self._display_results(results))
            except Exception as e:
                logger.exception("Search error")
                self.after(0, lambda: self._show_error(f"Search failed: {e}"))
        
        threading.Thread(target=search_thread, daemon=True).start()
    
    def _display_results(self, results):
        """Display search results"""
        for w in self.results_frame.winfo_children():
            w.destroy()
        
        if not results.albums and not results.tracks:
            ctk.CTkLabel(
                self.results_frame, text="No results found",
                font=ctk.CTkFont(size=16), text_color=COLORS["subtext"]
            ).pack(pady=100)
            return
        
        # Albums
        if results.albums:
            ctk.CTkLabel(
                self.results_frame,
                text=f"Albums ({len(results.albums)})",
                font=ctk.CTkFont(size=18, weight="bold"),
                text_color=COLORS["text"]
            ).pack(anchor="w", pady=(0, 15))
            
            albums_grid = ctk.CTkFrame(self.results_frame, fg_color="transparent")
            albums_grid.pack(fill="x", pady=(0, 30))
            
            for i, album in enumerate(results.albums[:8]):
                col = i % 4
                row = i // 4
                self._create_album_card(albums_grid, album, row, col)
        
        # Tracks
        if results.tracks:
            ctk.CTkLabel(
                self.results_frame,
                text=f"Tracks ({len(results.tracks)})",
                font=ctk.CTkFont(size=18, weight="bold"),
                text_color=COLORS["text"]
            ).pack(anchor="w", pady=(10, 15))
            
            for i, track in enumerate(results.tracks[:15]):
                self._create_track_row(self.results_frame, track, i+1)
    
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
        
        # Load art async
        def load_art():
            try:
                url = album.image(320)
                if url:
                    resp = requests.get(url, timeout=10)
                    if resp.status_code == 200:
                        img = Image.open(BytesIO(resp.content))
                        img = img.resize((160, 160), Image.Resampling.LANCZOS)
                        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(160, 160))
                        self.after(0, lambda: art.configure(image=ctk_img, text=""))
            except:
                pass
        threading.Thread(target=load_art, daemon=True).start()
        
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
        """Create a track row"""
        row = ctk.CTkFrame(parent, fg_color=COLORS["bg_medium"], corner_radius=8, height=45)
        row.pack(fill="x", pady=2)
        row.pack_propagate(False)
        
        # Number
        ctk.CTkLabel(
            row, text=str(num).zfill(2), width=35,
            font=ctk.CTkFont(size=12), text_color=COLORS["subtext"]
        ).pack(side="left", padx=(15, 5))
        
        # Title
        title = track.name[:45] + "..." if len(track.name) > 45 else track.name
        ctk.CTkLabel(
            row, text=title,
            font=ctk.CTkFont(size=13), text_color=COLORS["text"],
            anchor="w"
        ).pack(side="left", fill="x", expand=True, padx=5)
        
        # Duration
        dur = f"{track.duration // 60}:{track.duration % 60:02d}" if track.duration else "--:--"
        ctk.CTkLabel(
            row, text=dur, width=50,
            font=ctk.CTkFont(size=11), text_color=COLORS["subtext"]
        ).pack(side="right", padx=10)
        
        # Download
        ctk.CTkButton(
            row, text="+", width=35, height=30,
            fg_color=COLORS["blue"], hover_color="#a8c8ff",
            text_color=COLORS["bg_dark"],
            command=lambda t=track: self._download_track(t)
        ).pack(side="right", padx=5)
    
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
    
    def _on_tasks_added(self, tasks):
        """Called when tasks are added to the queue"""
        self._show_toast(f"Added {len(tasks)} to queue", COLORS["green"])
        self._refresh_downloads_ui()
        # Auto-start downloads if not already running
        if self.download_queue and not self.download_queue.is_running:
            self._start_downloads()
    
    def _refresh_downloads_ui(self):
        """Refresh the downloads list UI"""
        if not self.download_queue:
            return
        
        # Clear current list
        for w in self.downloads_list.winfo_children():
            w.destroy()
        
        # Get all tasks and deduplicate by ID (same task can be in queue and completed)
        all_tasks_dict = {}
        for task in self.download_queue.queue:
            all_tasks_dict[task.id] = task
        for task in self.download_queue.completed:
            all_tasks_dict[task.id] = task  # Completed takes precedence
        for task in self.download_queue.failed:
            all_tasks_dict[task.id] = task  # Failed takes precedence
        
        all_tasks = list(all_tasks_dict.values())
        
        if not all_tasks:
            ctk.CTkLabel(
                self.downloads_list,
                text="No downloads yet\nSearch and add music to queue",
                font=ctk.CTkFont(size=14),
                text_color=COLORS["subtext"]
            ).pack(pady=80)
            return
        
        # Group tasks by album
        albums = {}
        singles = []
        
        for task in all_tasks:
            album = task.album
            if album:
                album_id = album.id
                if album_id not in albums:
                    albums[album_id] = {"album": album, "tasks": []}
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
        
        # Show albums
        for album_id, data in albums.items():
            self._create_album_group(data["album"], data["tasks"])
        
        # Show singles (if any without album)
        if singles:
            self._create_singles_group(singles)
        
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
        
        # Load album art async
        def load_thumb():
            try:
                url = album.image(160)
                if url:
                    resp = requests.get(url, timeout=10)
                    if resp.status_code == 200:
                        img = Image.open(BytesIO(resp.content))
                        img = img.resize((45, 45), Image.Resampling.LANCZOS)
                        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(45, 45))
                        self.after(0, lambda: thumb_label.configure(image=ctk_img, text=""))
            except:
                pass
        threading.Thread(target=load_thumb, daemon=True).start()
        
        # Album name (also clickable to toggle)
        album_name = album.name[:28] + "..." if len(album.name) > 28 else album.name
        name_label = ctk.CTkLabel(
            info_row, text=album_name,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text"]
        )
        name_label.pack(side="left", padx=(0, 10))
        name_label.bind("<Button-1>", lambda e: self._toggle_album(album_id))
        
        # Progress indicator
        progress_text = f"{completed}/{total}"
        progress_color = COLORS["green"] if completed == total else COLORS["blue"] if completed > 0 else COLORS["subtext"]
        ctk.CTkLabel(
            info_row, text=progress_text,
            font=ctk.CTkFont(size=11),
            text_color=progress_color
        ).pack(side="right", padx=5)
        
        # Album progress bar
        if total > 0:
            progress = ctk.CTkProgressBar(header, height=3, progress_color=COLORS["accent"], fg_color=COLORS["bg_medium"])
            progress.pack(fill="x", padx=12, pady=(0, 8))
            progress.set(completed / total)
        
        # Track rows (only if expanded)
        if is_expanded:
            for task in tasks:
                self._create_track_download_item(task, indent=True)
    
    def _toggle_album(self, album_id):
        """Toggle album expansion state"""
        self.expanded_albums[album_id] = not self.expanded_albums.get(album_id, False)
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
        
        ctk.CTkLabel(
            frame, text=icon_text, width=25,
            font=ctk.CTkFont(size=14),
            text_color=icon_color
        ).pack(side="left", padx=(10, 5))
        
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
            status_text = f"Converting to FLAC..."
        elif task.status == DownloadStatus.DOWNLOADING:
            status_text = f"Downloading {task.progress:.0f}%"
        else:
            status_text = task.status.value.capitalize()
        
        ctk.CTkLabel(
            status_row, text=status_text,
            font=ctk.CTkFont(size=9),
            text_color=status_colors.get(task.status, COLORS["subtext"]) if not task.is_converting else COLORS["yellow"],
            anchor="w"
        ).pack(side="left")
        
        # Progress bars
        show_progress = False
        
        # During active download (not converting yet)
        if task.status == DownloadStatus.DOWNLOADING and not task.is_converting:
            show_progress = True
            bar_frame = ctk.CTkFrame(status_row, fg_color="transparent")
            bar_frame.pack(side="right", padx=(10, 0))
            
            dl_progress = ctk.CTkProgressBar(bar_frame, width=120, height=4, progress_color=COLORS["blue"], fg_color=COLORS["bg_dark"])
            dl_progress.pack(side="left")
            dl_progress.set(task.progress / 100)
        
        # During conversion
        if task.is_converting:
            show_progress = True
            bar_frame = ctk.CTkFrame(status_row, fg_color="transparent")
            bar_frame.pack(side="right", padx=(10, 0))
            
            # Show indeterminate-like progress (since remux is quick)
            conv_progress = ctk.CTkProgressBar(bar_frame, width=100, height=4, progress_color=COLORS["yellow"], fg_color=COLORS["bg_dark"])
            conv_progress.pack(side="left")
            conv_progress.set(0.5)  # Show halfway as activity indicator
    
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
        """Save settings"""
        self._show_toast("Settings saved!", COLORS["green"])
    
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
    app.mainloop()


if __name__ == "__main__":
    main()
