"""
Audio Player Module

Implements audio playback using GStreamer.

Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

# Try to import GStreamer
try:
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst, GLib
    Gst.init(None)
    GSTREAMER_AVAILABLE = True
except (ImportError, ValueError) as e:
    GSTREAMER_AVAILABLE = False
    logger.warning(f"GStreamer not available: {e}")


class PlayerState(Enum):
    """Player state enumeration."""
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    BUFFERING = "buffering"
    ERROR = "error"


@dataclass
class PlaybackInfo:
    """Current playback information."""
    state: PlayerState = PlayerState.STOPPED
    position: float = 0.0  # seconds
    duration: float = 0.0  # seconds
    volume: float = 1.0  # 0.0 to 1.0
    current_file: Optional[Path] = None
    
    @property
    def progress(self) -> float:
        """Get playback progress as percentage (0-100)."""
        if self.duration <= 0:
            return 0.0
        return (self.position / self.duration) * 100


@dataclass
class QueueItem:
    """Item in the playback queue."""
    file_path: Path
    title: str = ""
    
    def __post_init__(self):
        if not self.title:
            self.title = self.file_path.stem


class AudioPlayer:
    """
    Audio player using GStreamer playbin.
    
    Features:
    - Play, pause, stop, seek
    - Volume control
    - Playback queue
    - Gapless playback
    - Position/duration tracking
    """
    
    def __init__(self):
        """Initialize the audio player."""
        self._playbin = None
        self._state = PlayerState.STOPPED
        self._volume = 0.8
        self._current_file: Optional[Path] = None
        self._queue: List[QueueItem] = []
        self._queue_index = -1
        
        # Callbacks
        self._on_state_changed: Optional[Callable[[PlayerState], None]] = None
        self._on_position_changed: Optional[Callable[[float, float], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._on_eos: Optional[Callable[[], None]] = None
        
        if GSTREAMER_AVAILABLE:
            self._setup_pipeline()
    
    @property
    def is_available(self) -> bool:
        """Check if GStreamer is available."""
        return GSTREAMER_AVAILABLE
    
    @property
    def state(self) -> PlayerState:
        """Get current player state."""
        return self._state
    
    @property
    def volume(self) -> float:
        """Get current volume (0.0 to 1.0)."""
        return self._volume
    
    @volume.setter
    def volume(self, value: float) -> None:
        """Set volume (0.0 to 1.0)."""
        self._volume = max(0.0, min(1.0, value))
        if self._playbin:
            self._playbin.set_property('volume', self._volume)
    
    def _setup_pipeline(self) -> None:
        """Set up the GStreamer pipeline."""
        if not GSTREAMER_AVAILABLE:
            return
        
        # Create playbin element
        self._playbin = Gst.ElementFactory.make('playbin', 'player')
        
        if self._playbin is None:
            logger.error("Failed to create playbin element")
            return
        
        # Set initial volume
        self._playbin.set_property('volume', self._volume)
        
        # Connect to bus for messages
        bus = self._playbin.get_bus()
        bus.add_signal_watch()
        bus.connect('message::eos', self._on_bus_eos)
        bus.connect('message::error', self._on_bus_error)
        bus.connect('message::state-changed', self._on_bus_state_changed)
        
        # Connect about-to-finish for gapless playback
        self._playbin.connect('about-to-finish', self._on_about_to_finish)
        
        logger.info("GStreamer pipeline initialized")
    
    def load(self, file_path: Path) -> bool:
        """
        Load an audio file.
        
        Args:
            file_path: Path to the audio file
            
        Returns:
            bool: True if loaded successfully
        """
        if not GSTREAMER_AVAILABLE or not self._playbin:
            logger.warning("GStreamer not available")
            return False
        
        file_path = Path(file_path)
        
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return False
        
        # Stop current playback
        self.stop()
        
        # Set URI
        uri = file_path.as_uri()
        self._playbin.set_property('uri', uri)
        self._current_file = file_path
        
        logger.debug(f"Loaded: {file_path}")
        return True
    
    def play(self) -> bool:
        """
        Start or resume playback.
        
        Returns:
            bool: True if playback started
        """
        if not self._playbin:
            return False
        
        ret = self._playbin.set_state(Gst.State.PLAYING)
        success = ret != Gst.StateChangeReturn.FAILURE
        
        if success:
            self._state = PlayerState.PLAYING
            if self._on_state_changed:
                self._on_state_changed(self._state)
        
        return success
    
    def pause(self) -> bool:
        """
        Pause playback.
        
        Returns:
            bool: True if paused
        """
        if not self._playbin:
            return False
        
        ret = self._playbin.set_state(Gst.State.PAUSED)
        success = ret != Gst.StateChangeReturn.FAILURE
        
        if success:
            self._state = PlayerState.PAUSED
            if self._on_state_changed:
                self._on_state_changed(self._state)
        
        return success
    
    def stop(self) -> None:
        """Stop playback."""
        if self._playbin:
            self._playbin.set_state(Gst.State.NULL)
        
        self._state = PlayerState.STOPPED
        self._current_file = None
        
        if self._on_state_changed:
            self._on_state_changed(self._state)
    
    def seek(self, position: float) -> bool:
        """
        Seek to a position.
        
        Args:
            position: Position in seconds
            
        Returns:
            bool: True if seek was successful
        """
        if not self._playbin:
            return False
        
        # Convert to nanoseconds
        position_ns = int(position * Gst.SECOND)
        
        success = self._playbin.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            position_ns
        )
        
        return success
    
    def get_position(self) -> float:
        """
        Get current playback position.
        
        Returns:
            float: Position in seconds
        """
        if not self._playbin:
            return 0.0
        
        success, position = self._playbin.query_position(Gst.Format.TIME)
        
        if success:
            return position / Gst.SECOND
        return 0.0
    
    def get_duration(self) -> float:
        """
        Get duration of current file.
        
        Returns:
            float: Duration in seconds
        """
        if not self._playbin:
            return 0.0
        
        success, duration = self._playbin.query_duration(Gst.Format.TIME)
        
        if success:
            return duration / Gst.SECOND
        return 0.0
    
    def get_info(self) -> PlaybackInfo:
        """
        Get current playback information.
        
        Returns:
            PlaybackInfo: Current playback state
        """
        return PlaybackInfo(
            state=self._state,
            position=self.get_position(),
            duration=self.get_duration(),
            volume=self._volume,
            current_file=self._current_file,
        )
    
    # Queue management
    
    def queue_add(self, file_path: Path, title: str = "") -> None:
        """Add a file to the queue."""
        self._queue.append(QueueItem(file_path=Path(file_path), title=title))
    
    def queue_clear(self) -> None:
        """Clear the playback queue."""
        self._queue.clear()
        self._queue_index = -1
    
    def queue_next(self) -> bool:
        """
        Play the next item in the queue.
        
        Returns:
            bool: True if next item was loaded
        """
        if self._queue_index + 1 < len(self._queue):
            self._queue_index += 1
            item = self._queue[self._queue_index]
            if self.load(item.file_path):
                return self.play()
        return False
    
    def queue_previous(self) -> bool:
        """
        Play the previous item in the queue.
        
        Returns:
            bool: True if previous item was loaded
        """
        if self._queue_index > 0:
            self._queue_index -= 1
            item = self._queue[self._queue_index]
            if self.load(item.file_path):
                return self.play()
        return False
    
    def get_queue(self) -> List[QueueItem]:
        """Get the current queue."""
        return self._queue.copy()
    
    # Callbacks
    
    def set_on_state_changed(self, callback: Callable[[PlayerState], None]) -> None:
        """Set callback for state changes."""
        self._on_state_changed = callback
    
    def set_on_position_changed(self, callback: Callable[[float, float], None]) -> None:
        """Set callback for position changes (position, duration)."""
        self._on_position_changed = callback
    
    def set_on_error(self, callback: Callable[[str], None]) -> None:
        """Set callback for errors."""
        self._on_error = callback
    
    def set_on_eos(self, callback: Callable[[], None]) -> None:
        """Set callback for end of stream."""
        self._on_eos = callback
    
    # GStreamer bus handlers
    
    def _on_bus_eos(self, bus, message) -> None:
        """Handle end of stream."""
        logger.debug("End of stream")
        
        # Try to play next in queue (gapless)
        if not self.queue_next():
            self.stop()
        
        if self._on_eos:
            self._on_eos()
    
    def _on_bus_error(self, bus, message) -> None:
        """Handle error messages."""
        err, debug = message.parse_error()
        error_msg = f"GStreamer error: {err.message}"
        logger.error(f"{error_msg}\nDebug: {debug}")
        
        self._state = PlayerState.ERROR
        
        if self._on_error:
            self._on_error(error_msg)
    
    def _on_bus_state_changed(self, bus, message) -> None:
        """Handle state change messages."""
        if message.src != self._playbin:
            return
        
        old, new, pending = message.parse_state_changed()
        logger.debug(f"State changed: {old.value_nick} -> {new.value_nick}")
    
    def _on_about_to_finish(self, playbin) -> None:
        """Handle about-to-finish for gapless playback."""
        # Queue next track if available
        if self._queue_index + 1 < len(self._queue):
            next_item = self._queue[self._queue_index + 1]
            uri = next_item.file_path.as_uri()
            playbin.set_property('uri', uri)
            self._queue_index += 1
            self._current_file = next_item.file_path
            logger.debug(f"Gapless: queued {next_item.file_path}")
    
    def cleanup(self) -> None:
        """Clean up resources."""
        self.stop()
        if self._playbin:
            self._playbin.set_state(Gst.State.NULL)
            self._playbin = None


# Global player instance
_player: Optional[AudioPlayer] = None


def get_audio_player() -> AudioPlayer:
    """Get the global audio player."""
    global _player
    if _player is None:
        _player = AudioPlayer()
    return _player
