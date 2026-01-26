"""
Core utility functions for transcriptionist_v3.
Provides common formatting and helper functions used across the application.
"""

from typing import Union


def format_file_size(size: int) -> str:
    """
    Format a file size in bytes to a human-readable string.
    
    Args:
        size: File size in bytes
        
    Returns:
        Formatted string like "1.5 MB", "256 KB", or "512 B"
    """
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"


def format_duration(seconds: Union[int, float]) -> str:
    """
    Format a duration in seconds to MM:SS or HH:MM:SS format.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted string like "03:45" or "1:23:45"
    """
    if seconds < 0:
        return "-"
    
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"


def format_sample_rate(sample_rate: int) -> str:
    """
    Format a sample rate to a human-readable string.
    
    Args:
        sample_rate: Sample rate in Hz
        
    Returns:
        Formatted string like "48.0k" or "44.1k"
    """
    if sample_rate <= 0:
        return "-"
    return f"{sample_rate / 1000:.1f}k"


def format_channels(channels: int) -> str:
    """
    Format audio channel count to a human-readable string.
    
    Args:
        channels: Number of audio channels
        
    Returns:
        Formatted string like "单声道", "立体声", or "5.1 声道"
    """
    if channels == 1:
        return "单声道"
    elif channels == 2:
        return "立体声"
    elif channels > 0:
        return f"{channels} 声道"
    else:
        return "-"


def format_bit_depth(bit_depth: int) -> str:
    """
    Format bit depth to a human-readable string.
    
    Args:
        bit_depth: Bit depth (e.g., 16, 24, 32)
        
    Returns:
        Formatted string like "24 bit"
    """
    if bit_depth > 0:
        return f"{bit_depth} bit"
    else:
        return "-"
