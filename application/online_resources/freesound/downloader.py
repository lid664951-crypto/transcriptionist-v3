"""
Freesound Downloader

Handles downloading sounds from Freesound.org with progress tracking,
queue management, and metadata import.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime
import aiohttp
import json

from .models import (
    FreesoundSound,
    FreesoundDownloadItem,
    FreesoundSettings,
    LICENSE_INFO,
)
from .client import FreesoundClient, FreesoundError

logger = logging.getLogger(__name__)

# Type alias for progress callback
ProgressCallback = Callable[[FreesoundDownloadItem], None]


class FreesoundDownloader:
    """
    Manages downloading sounds from Freesound.org.
    
    Features:
    - Download queue with concurrent downloads
    - Progress tracking
    - Automatic metadata sidecar file creation
    - License information preservation
    """
    
    def __init__(
        self,
        client: FreesoundClient,
        settings: FreesoundSettings,
        progress_callback: Optional[ProgressCallback] = None,
    ):
        """
        Initialize downloader.
        
        Args:
            client: FreesoundClient instance
            settings: Download settings
            progress_callback: Optional callback for progress updates
        """
        self.client = client
        self.settings = settings
        self.progress_callback = progress_callback
        
        self._queue: List[FreesoundDownloadItem] = []
        self._active_downloads: Dict[int, FreesoundDownloadItem] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    @property
    def queue(self) -> List[FreesoundDownloadItem]:
        """Get current download queue."""
        return self._queue.copy()
    
    @property
    def active_count(self) -> int:
        """Get number of active downloads."""
        return len(self._active_downloads)
    
    @property
    def pending_count(self) -> int:
        """Get number of pending downloads."""
        return sum(1 for item in self._queue if item.status == 'pending')
    
    async def add_to_queue(self, sound: FreesoundSound) -> FreesoundDownloadItem:
        """
        Add a sound to the download queue.
        
        Args:
            sound: FreesoundSound to download
        
        Returns:
            FreesoundDownloadItem representing the queued download
        """
        async with self._lock:
            # Check if already in queue
            for item in self._queue:
                if item.sound.id == sound.id:
                    logger.debug(f"Sound {sound.id} already in queue")
                    return item
            
            item = FreesoundDownloadItem(sound=sound, status='pending')
            self._queue.append(item)
            logger.info(f"Added sound {sound.id} ({sound.name}) to download queue")
            
            # Start processing if not already running
            if not self._running:
                self._start_processing()
            
            return item
    
    async def add_batch_to_queue(self, sounds: List[FreesoundSound]) -> List[FreesoundDownloadItem]:
        """
        Add multiple sounds to the download queue.
        
        Args:
            sounds: List of FreesoundSound objects to download
        
        Returns:
            List of FreesoundDownloadItem objects
        """
        items = []
        for sound in sounds:
            item = await self.add_to_queue(sound)
            items.append(item)
        return items
    
    async def cancel_download(self, sound_id: int) -> bool:
        """
        Cancel a download.
        
        Args:
            sound_id: ID of the sound to cancel
        
        Returns:
            True if cancelled, False if not found
        """
        async with self._lock:
            # Check active downloads
            if sound_id in self._active_downloads:
                item = self._active_downloads[sound_id]
                item.status = 'cancelled'
                self._notify_progress(item)
                return True
            
            # Check queue
            for item in self._queue:
                if item.sound.id == sound_id and item.status == 'pending':
                    item.status = 'cancelled'
                    self._notify_progress(item)
                    return True
            
            return False
    
    async def clear_completed(self) -> int:
        """
        Remove completed and failed downloads from queue.
        
        Returns:
            Number of items removed
        """
        async with self._lock:
            original_count = len(self._queue)
            self._queue = [
                item for item in self._queue
                if item.status in ('pending', 'downloading')
            ]
            return original_count - len(self._queue)
    
    async def retry_failed(self) -> int:
        """
        Retry all failed downloads.
        
        Returns:
            Number of downloads retried
        """
        count = 0
        async with self._lock:
            for item in self._queue:
                if item.status == 'failed':
                    item.status = 'pending'
                    item.error = None
                    item.progress = 0.0
                    count += 1
            
            if count > 0 and not self._running:
                self._start_processing()
        
        return count
    
    def _start_processing(self) -> None:
        """Start the download processing task."""
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._process_queue())
    
    async def stop(self) -> None:
        """Stop the downloader."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _process_queue(self) -> None:
        """Process the download queue."""
        logger.info("Starting download queue processing")
        
        while self._running:
            # Get next pending item
            item = await self._get_next_pending()
            if item is None:
                # No more pending items, wait a bit
                await asyncio.sleep(0.5)
                
                # Check if we should stop
                if self.pending_count == 0 and self.active_count == 0:
                    break
                continue
            
            # Check concurrent download limit
            if self.active_count >= self.settings.max_concurrent_downloads:
                await asyncio.sleep(0.5)
                continue
            
            # Start download
            asyncio.create_task(self._download_item(item))
        
        self._running = False
        logger.info("Download queue processing stopped")
    
    async def _get_next_pending(self) -> Optional[FreesoundDownloadItem]:
        """Get the next pending download item."""
        async with self._lock:
            for item in self._queue:
                if item.status == 'pending':
                    return item
        return None
    
    async def _download_item(self, item: FreesoundDownloadItem) -> None:
        """
        Download a single item.
        
        Args:
            item: FreesoundDownloadItem to download
        """
        sound = item.sound
        
        async with self._lock:
            item.status = 'downloading'
            item.started_at = datetime.now()
            self._active_downloads[sound.id] = item
        
        self._notify_progress(item)
        
        try:
            # Get download URL
            download_url = await self.client.get_download_url(sound.id)
            
            # Determine save path
            save_dir = Path(self.settings.download_path)
            save_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate filename
            filename = self._generate_filename(sound)
            save_path = save_dir / filename
            
            # Handle filename conflicts
            save_path = self._resolve_conflict(save_path)
            
            # Download file
            await self._download_file(download_url, save_path, item)
            
            # Create metadata sidecar
            await self._create_metadata_sidecar(sound, save_path)
            
            # Update item status
            async with self._lock:
                item.status = 'completed'
                item.local_path = str(save_path)
                item.completed_at = datetime.now()
                del self._active_downloads[sound.id]
            
            logger.info(f"Downloaded sound {sound.id} to {save_path}")
            self._notify_progress(item)
        
        except asyncio.CancelledError:
            async with self._lock:
                item.status = 'cancelled'
                if sound.id in self._active_downloads:
                    del self._active_downloads[sound.id]
            self._notify_progress(item)
            raise
        
        except Exception as e:
            logger.error(f"Failed to download sound {sound.id}: {e}")
            async with self._lock:
                item.status = 'failed'
                item.error = str(e)
                if sound.id in self._active_downloads:
                    del self._active_downloads[sound.id]
            self._notify_progress(item)
    
    async def _download_file(
        self,
        url: str,
        save_path: Path,
        item: FreesoundDownloadItem,
    ) -> None:
        """
        Download a file with progress tracking.
        
        Args:
            url: Download URL
            save_path: Path to save the file
            item: Download item for progress updates
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise FreesoundError(f"Download failed with status {response.status}")
                
                total_size = int(response.headers.get('Content-Length', 0))
                downloaded = 0
                
                with open(save_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(8192):
                        if item.status == 'cancelled':
                            raise asyncio.CancelledError()
                        
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if total_size > 0:
                            item.progress = downloaded / total_size
                            self._notify_progress(item)
    
    def _generate_filename(self, sound: FreesoundSound) -> str:
        """
        Generate filename for downloaded sound.
        
        Args:
            sound: FreesoundSound object
        
        Returns:
            Generated filename
        """
        if self.settings.keep_original_name:
            # Use original name from Freesound
            name = sound.name
        else:
            # Use translated name if available, otherwise original
            name = sound.name_zh or sound.name
        
        # Clean filename
        name = self._sanitize_filename(name)
        
        # Add extension if not present
        ext = f".{sound.type}" if sound.type else ".wav"
        if not name.lower().endswith(ext.lower()):
            name = f"{name}{ext}"
        
        return name
    
    def _sanitize_filename(self, name: str) -> str:
        """
        Sanitize filename by removing invalid characters.
        
        Args:
            name: Original filename
        
        Returns:
            Sanitized filename
        """
        # Characters not allowed in filenames
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        
        # Remove leading/trailing spaces and dots
        name = name.strip(' .')
        
        # Limit length
        if len(name) > 200:
            name = name[:200]
        
        return name or 'untitled'
    
    def _resolve_conflict(self, path: Path) -> Path:
        """
        Resolve filename conflict by adding a number suffix.
        
        Args:
            path: Original file path
        
        Returns:
            Path with conflict resolved
        """
        if not path.exists():
            return path
        
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        
        counter = 1
        while True:
            new_path = parent / f"{stem}_{counter}{suffix}"
            if not new_path.exists():
                return new_path
            counter += 1
            if counter > 1000:
                raise FreesoundError("Too many filename conflicts")
    
    async def _create_metadata_sidecar(
        self,
        sound: FreesoundSound,
        audio_path: Path,
    ) -> None:
        """
        Create a JSON sidecar file with metadata.
        
        Args:
            sound: FreesoundSound object
            audio_path: Path to the downloaded audio file
        """
        sidecar_path = audio_path.with_suffix(audio_path.suffix + '.json')
        
        metadata = {
            'source': 'freesound',
            'freesound_id': sound.id,
            'original_name': sound.name,
            'description': sound.description,
            'username': sound.username,
            'license': sound.license,
            'license_url': sound.license_url,
            'attribution': sound.attribution_text,
            'duration': sound.duration,
            'channels': sound.channels,
            'samplerate': sound.samplerate,
            'bitdepth': sound.bitdepth,
            'tags': sound.tags,
            'avg_rating': sound.avg_rating,
            'num_downloads': sound.num_downloads,
            'downloaded_at': datetime.now().isoformat(),
            'freesound_url': f"https://freesound.org/sounds/{sound.id}/",
        }
        
        # Add translated fields if available
        if sound.name_zh:
            metadata['name_zh'] = sound.name_zh
        if sound.description_zh:
            metadata['description_zh'] = sound.description_zh
        if sound.tags_zh:
            metadata['tags_zh'] = sound.tags_zh
        
        with open(sidecar_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        logger.debug(f"Created metadata sidecar: {sidecar_path}")
    
    def _notify_progress(self, item: FreesoundDownloadItem) -> None:
        """Notify progress callback if set."""
        if self.progress_callback:
            try:
                self.progress_callback(item)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")


async def download_single(
    client: FreesoundClient,
    sound: FreesoundSound,
    save_path: str,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> str:
    """
    Download a single sound without using the queue.
    
    Args:
        client: FreesoundClient instance
        sound: FreesoundSound to download
        save_path: Directory to save the file
        progress_callback: Optional callback for progress (0.0 to 1.0)
    
    Returns:
        Path to the downloaded file
    """
    download_url = await client.get_download_url(sound.id)
    
    save_dir = Path(save_path)
    save_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"{sound.name}.{sound.type}"
    file_path = save_dir / filename
    
    async with aiohttp.ClientSession() as session:
        async with session.get(download_url) as response:
            if response.status != 200:
                raise FreesoundError(f"Download failed with status {response.status}")
            
            total_size = int(response.headers.get('Content-Length', 0))
            downloaded = 0
            
            with open(file_path, 'wb') as f:
                async for chunk in response.content.iter_chunked(8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    if progress_callback and total_size > 0:
                        progress_callback(downloaded / total_size)
    
    return str(file_path)
