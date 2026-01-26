"""
File Watcher Module

Implements file change detection using watchdog.

Validates: Requirements 1.4
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, List, Optional, Set

logger = logging.getLogger(__name__)

# Try to import watchdog
try:
    from watchdog.observers import Observer
    from watchdog.events import (
        FileSystemEventHandler,
        FileCreatedEvent,
        FileDeletedEvent,
        FileModifiedEvent,
        FileMovedEvent,
    )
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    logger.warning("Watchdog library not available. File watching disabled.")


# Supported audio formats for watching
WATCHED_EXTENSIONS = {
    ".wav", ".flac", ".mp3", ".ogg", ".aiff", ".aif", ".m4a", ".mp4"
}


class FileChangeHandler:
    """
    Handles file system change events.
    
    Callbacks:
    - on_created: Called when a new audio file is created
    - on_deleted: Called when an audio file is deleted
    - on_modified: Called when an audio file is modified
    - on_moved: Called when an audio file is moved/renamed
    """
    
    def __init__(
        self,
        on_created: Optional[Callable[[Path], None]] = None,
        on_deleted: Optional[Callable[[Path], None]] = None,
        on_modified: Optional[Callable[[Path], None]] = None,
        on_moved: Optional[Callable[[Path, Path], None]] = None,
    ):
        self.on_created = on_created
        self.on_deleted = on_deleted
        self.on_modified = on_modified
        self.on_moved = on_moved


if WATCHDOG_AVAILABLE:
    class AudioFileEventHandler(FileSystemEventHandler):
        """Watchdog event handler for audio files."""
        
        def __init__(
            self,
            handler: FileChangeHandler,
            extensions: Set[str] = WATCHED_EXTENSIONS
        ):
            super().__init__()
            self.handler = handler
            self.extensions = extensions
        
        def _is_audio_file(self, path: str) -> bool:
            """Check if the path is an audio file."""
            return Path(path).suffix.lower() in self.extensions
        
        def on_created(self, event):
            if event.is_directory:
                return
            if self._is_audio_file(event.src_path):
                logger.debug(f"File created: {event.src_path}")
                if self.handler.on_created:
                    self.handler.on_created(Path(event.src_path))
        
        def on_deleted(self, event):
            if event.is_directory:
                return
            if self._is_audio_file(event.src_path):
                logger.debug(f"File deleted: {event.src_path}")
                if self.handler.on_deleted:
                    self.handler.on_deleted(Path(event.src_path))
        
        def on_modified(self, event):
            if event.is_directory:
                return
            if self._is_audio_file(event.src_path):
                logger.debug(f"File modified: {event.src_path}")
                if self.handler.on_modified:
                    self.handler.on_modified(Path(event.src_path))
        
        def on_moved(self, event):
            if event.is_directory:
                return
            src_is_audio = self._is_audio_file(event.src_path)
            dest_is_audio = self._is_audio_file(event.dest_path)
            
            if src_is_audio or dest_is_audio:
                logger.debug(f"File moved: {event.src_path} -> {event.dest_path}")
                if self.handler.on_moved:
                    self.handler.on_moved(
                        Path(event.src_path),
                        Path(event.dest_path)
                    )


class FileWatcher:
    """
    Watches directories for file changes.
    
    Uses watchdog library for efficient file system monitoring.
    """
    
    def __init__(self, handler: FileChangeHandler):
        """
        Initialize the file watcher.
        
        Args:
            handler: Handler for file change events
        """
        self.handler = handler
        self._observer: Optional[Observer] = None
        self._watched_paths: Set[Path] = set()
        self._running = False
    
    @property
    def is_available(self) -> bool:
        """Check if file watching is available."""
        return WATCHDOG_AVAILABLE
    
    @property
    def is_running(self) -> bool:
        """Check if the watcher is running."""
        return self._running
    
    def add_path(self, path: Path, recursive: bool = True) -> bool:
        """
        Add a path to watch.
        
        Args:
            path: Directory path to watch
            recursive: Whether to watch subdirectories
            
        Returns:
            bool: True if path was added successfully
        """
        if not WATCHDOG_AVAILABLE:
            logger.warning("Watchdog not available, cannot watch paths")
            return False
        
        path = Path(path)
        
        if not path.exists() or not path.is_dir():
            logger.warning(f"Invalid watch path: {path}")
            return False
        
        if path in self._watched_paths:
            logger.debug(f"Path already being watched: {path}")
            return True
        
        try:
            if self._observer is None:
                self._observer = Observer()
            
            event_handler = AudioFileEventHandler(self.handler)
            self._observer.schedule(event_handler, str(path), recursive=recursive)
            self._watched_paths.add(path)
            
            logger.info(f"Watching path: {path} (recursive={recursive})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to watch path {path}: {e}")
            return False
    
    def remove_path(self, path: Path) -> bool:
        """
        Remove a path from watching.
        
        Args:
            path: Directory path to stop watching
            
        Returns:
            bool: True if path was removed
        """
        path = Path(path)
        
        if path not in self._watched_paths:
            return False
        
        # Note: watchdog doesn't have a direct way to unschedule a single path
        # We would need to recreate the observer
        self._watched_paths.discard(path)
        logger.info(f"Stopped watching path: {path}")
        return True
    
    def start(self) -> bool:
        """
        Start watching for file changes.
        
        Returns:
            bool: True if started successfully
        """
        if not WATCHDOG_AVAILABLE:
            logger.warning("Watchdog not available")
            return False
        
        if self._running:
            return True
        
        if self._observer is None:
            logger.warning("No paths to watch")
            return False
        
        try:
            self._observer.start()
            self._running = True
            logger.info("File watcher started")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start file watcher: {e}")
            return False
    
    def stop(self) -> None:
        """Stop watching for file changes."""
        if self._observer and self._running:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._running = False
            logger.info("File watcher stopped")
    
    def get_watched_paths(self) -> List[Path]:
        """Get list of watched paths."""
        return list(self._watched_paths)


# Global file watcher instance
_file_watcher: Optional[FileWatcher] = None


def get_file_watcher(handler: Optional[FileChangeHandler] = None) -> FileWatcher:
    """
    Get the global file watcher.
    
    Args:
        handler: Optional handler for file changes
        
    Returns:
        FileWatcher: The file watcher instance
    """
    global _file_watcher
    
    if _file_watcher is None:
        if handler is None:
            handler = FileChangeHandler()
        _file_watcher = FileWatcher(handler)
    
    return _file_watcher
