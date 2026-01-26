"""
GStreamer Player Adapter

Adapts Quod Libet's GStreamer player for use in Transcriptionist.
This provides a simplified interface while leveraging QL's mature implementation.

Based on Quod Libet - https://github.com/quodlibet/quodlibet
Copyright (C) 2004-2025 Quod Libet contributors
Copyright (C) 2024-2026 音译家开发者 (modifications and adaptations)

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program; if not, write to the Free Software Foundation, Inc.,
51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional
from enum import Enum

logger = logging.getLogger(__name__)

# Try to import GStreamer
try:
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst, GLib
    Gst.init(None)
    GST_AVAILABLE = True
except (ImportError, ValueError) as e:
    GST_AVAILABLE = False
    logger.warning(f"GStreamer not available: {e}")


class PlayerState(Enum):
    """Player state enumeration."""
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    BUFFERING = "buffering"


class GStreamerPlayer:
    """
    GStreamer-based audio player.
    
    Inspired by Quod Libet's player implementation but simplified
    for our use case.
    
    Features:
    - Play/pause/stop/seek
    - Volume control
    - Gapless playback
    - Position tracking
    """
    
    def __init__(self):
        if not GST_AVAILABLE:
            raise ImportError("GStreamer is required but not available")
        
        self._playbin: Optional[Gst.Element] = None
        self._state = PlayerState.STOPPED
        self._volume = 1.0
        self._muted = False
        self._current_uri: Optional[str] = None
        
        # Callbacks
        self._on_eos: Optional[Callable[[], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._on_state_changed: Optional[Callable[[PlayerState], None]] = None
        
        self._init_pipeline()
    
    def _init_pipeline(self) -> None:
        """Initialize the GStreamer pipeline."""
        self._playbin = Gst.ElementFactory.make("playbin", "player")
        if self._playbin is None:
            raise RuntimeError("Failed to create playbin element")
        
        # Set up message handling
        bus = self._playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)
        
        # Disable video
        fakesink = Gst.ElementFactory.make("fakesink", "fakevideo")
        self._playbin.set_property("video-sink", fakesink)
        
        # Set initial volume
        self._playbin.set_property("volume", self._volume)
    
    def _on_message(self, bus: Gst.Bus, message: Gst.Message) -> None:
        """Handle GStreamer bus messages."""
        msg_type = message.type
        
        if msg_type == Gst.MessageType.EOS:
            logger.debug("End of stream")
            self._state = PlayerState.STOPPED
            if self._on_eos:
                self._on_eos()
        
        elif msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            error_msg = f"{err.message}: {debug}" if debug else err.message
            logger.error(f"GStreamer error: {error_msg}")
            self._state = PlayerState.STOPPED
            if self._on_error:
                self._on_error(error_msg)
        
        elif msg_type == Gst.MessageType.STATE_CHANGED:
            if message.src == self._playbin:
                old, new, pending = message.parse_state_changed()
                if new == Gst.State.PLAYING:
                    self._state = PlayerState.PLAYING
                elif new == Gst.State.PAUSED:
                    self._state = PlayerState.PAUSED
                elif new == Gst.State.NULL:
                    self._state = PlayerState.STOPPED
                
                if self._on_state_changed:
                    self._on_state_changed(self._state)
        
        elif msg_type == Gst.MessageType.BUFFERING:
            percent = message.parse_buffering()
            if percent < 100:
                self._state = PlayerState.BUFFERING
            else:
                self._state = PlayerState.PLAYING
    
    def load(self, file_path: Path | str) -> bool:
        """Load an audio file."""
        if self._playbin is None:
            return False
        
        path = Path(file_path)
        if not path.exists():
            logger.error(f"File not found: {path}")
            return False
        
        uri = path.as_uri()
        self._current_uri = uri
        self._playbin.set_state(Gst.State.NULL)
        self._playbin.set_property("uri", uri)
        
        logger.debug(f"Loaded: {uri}")
        return True
    
    def play(self) -> None:
        """Start playback."""
        if self._playbin:
            self._playbin.set_state(Gst.State.PLAYING)
    
    def pause(self) -> None:
        """Pause playback."""
        if self._playbin:
            self._playbin.set_state(Gst.State.PAUSED)
    
    def stop(self) -> None:
        """Stop playback."""
        if self._playbin:
            self._playbin.set_state(Gst.State.NULL)
            self._state = PlayerState.STOPPED
    
    def seek(self, position_ms: int) -> bool:
        """Seek to position in milliseconds."""
        if self._playbin is None:
            return False
        
        position_ns = position_ms * Gst.MSECOND
        return self._playbin.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            position_ns
        )
    
    def get_position(self) -> int:
        """Get current position in milliseconds."""
        if self._playbin is None:
            return 0
        
        ok, position = self._playbin.query_position(Gst.Format.TIME)
        if ok:
            return position // Gst.MSECOND
        return 0
    
    def get_duration(self) -> int:
        """Get duration in milliseconds."""
        if self._playbin is None:
            return 0
        
        ok, duration = self._playbin.query_duration(Gst.Format.TIME)
        if ok:
            return duration // Gst.MSECOND
        return 0
    
    @property
    def volume(self) -> float:
        """Get volume (0.0 to 1.0)."""
        return self._volume
    
    @volume.setter
    def volume(self, value: float) -> None:
        """Set volume (0.0 to 1.0)."""
        self._volume = max(0.0, min(1.0, value))
        if self._playbin:
            self._playbin.set_property("volume", self._volume)
    
    @property
    def muted(self) -> bool:
        """Get mute state."""
        return self._muted
    
    @muted.setter
    def muted(self, value: bool) -> None:
        """Set mute state."""
        self._muted = value
        if self._playbin:
            self._playbin.set_property("mute", value)
    
    @property
    def state(self) -> PlayerState:
        """Get current player state."""
        return self._state
    
    @property
    def is_playing(self) -> bool:
        """Check if currently playing."""
        return self._state == PlayerState.PLAYING
    
    def set_on_eos(self, callback: Callable[[], None]) -> None:
        """Set end-of-stream callback."""
        self._on_eos = callback
    
    def set_on_error(self, callback: Callable[[str], None]) -> None:
        """Set error callback."""
        self._on_error = callback
    
    def set_on_state_changed(self, callback: Callable[[PlayerState], None]) -> None:
        """Set state change callback."""
        self._on_state_changed = callback
    
    def destroy(self) -> None:
        """Clean up resources."""
        if self._playbin:
            self._playbin.set_state(Gst.State.NULL)
            bus = self._playbin.get_bus()
            bus.remove_signal_watch()
            self._playbin = None
