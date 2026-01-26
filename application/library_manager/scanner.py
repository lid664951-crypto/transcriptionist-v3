"""
Library Scanner Module

Implements directory scanning with async file discovery and metadata extraction.

Validates: Requirements 1.1, 1.2, 1.4, 1.6
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Callable, List, Optional, Set

logger = logging.getLogger(__name__)

# Supported audio formats
SUPPORTED_FORMATS = {
    ".wav", ".flac", ".mp3", ".ogg", ".aiff", ".aif", ".m4a", ".mp4"
}


@dataclass
class ScanProgress:
    """Progress information for a scan operation."""
    total_files: int = 0
    scanned_files: int = 0
    current_file: str = ""
    errors: List[str] = field(default_factory=list)
    
    @property
    def progress_percent(self) -> float:
        if self.total_files == 0:
            return 0.0
        return (self.scanned_files / self.total_files) * 100


@dataclass
class ScanResult:
    """Result of a directory scan."""
    path: Path
    files_found: int = 0
    files_added: int = 0
    files_updated: int = 0
    files_removed: int = 0
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class LibraryScanner:
    """
    Scans directories for audio files.
    
    Features:
    - Async file discovery
    - Parallel metadata extraction
    - Progress callbacks
    - Duplicate detection via content hash
    """
    
    def __init__(
        self,
        max_workers: int = 4,
        supported_formats: Optional[Set[str]] = None
    ):
        """
        Initialize the scanner.
        
        Args:
            max_workers: Maximum number of parallel workers
            supported_formats: Set of supported file extensions
        """
        self.max_workers = max_workers
        self.supported_formats = supported_formats or SUPPORTED_FORMATS
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._cancelled = False
    
    async def scan_directory(
        self,
        path: Path,
        recursive: bool = True,
        progress_callback: Optional[Callable[[ScanProgress], None]] = None
    ) -> ScanResult:
        """
        Scan a directory for audio files.
        
        Args:
            path: Directory path to scan
            recursive: Whether to scan subdirectories
            progress_callback: Callback for progress updates
            
        Returns:
            ScanResult: Results of the scan
        """
        start_time = datetime.now()
        self._cancelled = False
        
        result = ScanResult(path=path)
        progress = ScanProgress()
        
        try:
            # First pass: count files
            audio_files = []
            async for file_path in self._discover_files(path, recursive):
                if self._cancelled:
                    break
                audio_files.append(file_path)
            
            progress.total_files = len(audio_files)
            result.files_found = len(audio_files)
            
            if progress_callback:
                progress_callback(progress)
            
            # Second pass: process files
            for file_path in audio_files:
                if self._cancelled:
                    break
                
                progress.current_file = str(file_path)
                
                try:
                    # Process file (metadata extraction happens in library manager)
                    progress.scanned_files += 1
                    
                except Exception as e:
                    error_msg = f"Error processing {file_path}: {e}"
                    progress.errors.append(error_msg)
                    result.errors.append(error_msg)
                    logger.warning(error_msg)
                
                if progress_callback:
                    progress_callback(progress)
            
        except Exception as e:
            error_msg = f"Scan error: {e}"
            result.errors.append(error_msg)
            logger.error(error_msg)
        
        result.duration_seconds = (datetime.now() - start_time).total_seconds()
        return result
    
    async def _discover_files(
        self,
        path: Path,
        recursive: bool
    ) -> AsyncIterator[Path]:
        """
        Discover audio files in a directory.
        
        Args:
            path: Directory to scan
            recursive: Whether to scan subdirectories
            
        Yields:
            Path: Audio file paths
        """
        path = Path(path)
        
        if not path.exists():
            logger.warning(f"Path does not exist: {path}")
            return
        
        if not path.is_dir():
            logger.warning(f"Path is not a directory: {path}")
            return
        
        # Use thread pool for file system operations
        loop = asyncio.get_event_loop()
        
        if recursive:
            # Walk directory tree
            for root, dirs, files in os.walk(path):
                if self._cancelled:
                    break
                
                for filename in files:
                    if self._cancelled:
                        break
                    
                    file_path = Path(root) / filename
                    if self._is_audio_file(file_path):
                        yield file_path
                
                # Allow other tasks to run
                await asyncio.sleep(0)
        else:
            # Only scan top-level directory
            for item in path.iterdir():
                if self._cancelled:
                    break
                
                if item.is_file() and self._is_audio_file(item):
                    yield item
    
    def _is_audio_file(self, path: Path) -> bool:
        """Check if a file is a supported audio format."""
        return path.suffix.lower() in self.supported_formats
    
    def cancel(self) -> None:
        """Cancel the current scan operation."""
        self._cancelled = True
    
    def shutdown(self) -> None:
        """Shutdown the scanner and release resources."""
        self._executor.shutdown(wait=False)


def calculate_content_hash(file_path: Path, chunk_size: int = 65536) -> str:
    """
    Calculate SHA-256 hash of file content.
    
    Args:
        file_path: Path to the file
        chunk_size: Size of chunks to read
        
    Returns:
        str: Hexadecimal hash string
    """
    sha256 = hashlib.sha256()
    
    with open(file_path, 'rb') as f:
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            sha256.update(data)
    
    return sha256.hexdigest()


async def calculate_content_hash_async(
    file_path: Path,
    executor: Optional[ThreadPoolExecutor] = None
) -> str:
    """
    Calculate content hash asynchronously.
    
    Args:
        file_path: Path to the file
        executor: Thread pool executor
        
    Returns:
        str: Hexadecimal hash string
    """
    loop = asyncio.get_event_loop()
    
    if executor:
        return await loop.run_in_executor(
            executor, calculate_content_hash, file_path
        )
    else:
        return await loop.run_in_executor(
            None, calculate_content_hash, file_path
        )
