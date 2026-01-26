"""
Playback Manager Module

Provides audio playback functionality using GStreamer.
"""

from .player import (
    AudioPlayer,
    PlayerState,
    PlaybackInfo,
    QueueItem,
    get_audio_player,
    GSTREAMER_AVAILABLE,
)

__all__ = [
    "AudioPlayer",
    "PlayerState",
    "PlaybackInfo",
    "QueueItem",
    "get_audio_player",
    "GSTREAMER_AVAILABLE",
]
