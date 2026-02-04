"""
Metadata Extractor Module

Extracts audio metadata using the Mutagen library.

Validates: Requirements 1.2, 1.6
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from transcriptionist_v3.domain.models import AudioMetadata

logger = logging.getLogger(__name__)

# Try to import mutagen
try:
    import mutagen
    from mutagen.wave import WAVE
    from mutagen.flac import FLAC
    from mutagen.mp3 import MP3
    from mutagen.oggvorbis import OggVorbis
    from mutagen.aiff import AIFF
    from mutagen.mp4 import MP4
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False
    logger.warning("Mutagen library not available. Metadata extraction will be limited.")


class MetadataExtractor:
    """
    Extracts metadata from audio files using Mutagen.
    
    Supports: WAV, FLAC, MP3, OGG, AIFF, M4A
    """
    
    def __init__(self):
        """Initialize the metadata extractor."""
        if not MUTAGEN_AVAILABLE:
            logger.warning("Mutagen not available, using fallback extraction")
    
    def extract(self, file_path: Path, store_raw: bool = False) -> Optional[AudioMetadata]:
        """
        Extract metadata from an audio file.
        P1 优化：默认 store_raw=False，仅提取音效相关字段（comment、original_filename、info），
        百万级导入时避免 dict(audio.tags) 全量解析，显著缩短耗时。
        
        Args:
            file_path: Path to the audio file
            store_raw: 若 True 则填充 metadata.raw（完整标签字典），用于需要展示全部 tag 的场景
            
        Returns:
            AudioMetadata: Extracted metadata, or None if extraction failed
        """
        file_path = Path(file_path)

        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return None

        try:
            if MUTAGEN_AVAILABLE:
                return self._extract_with_mutagen(file_path, store_raw=store_raw)
            else:
                return self._extract_fallback(file_path)

        except Exception as e:
            logger.error(f"Failed to extract metadata from {file_path}: {e}")
            return None

    def _extract_with_mutagen(self, file_path: Path, store_raw: bool = False) -> AudioMetadata:
        """Extract metadata using Mutagen library."""
        suffix = file_path.suffix.lower()
        
        metadata = AudioMetadata()
        metadata.format = suffix.lstrip('.')
        
        try:
            audio = mutagen.File(file_path)
            
            if audio is None:
                logger.warning(f"Mutagen could not identify file: {file_path}")
                return self._extract_fallback(file_path)
            
            # Extract common properties
            if hasattr(audio, 'info'):
                info = audio.info
                
                # Duration
                if hasattr(info, 'length'):
                    metadata.duration = float(info.length)
                
                # Sample rate
                if hasattr(info, 'sample_rate'):
                    metadata.sample_rate = int(info.sample_rate)
                
                # Channels
                if hasattr(info, 'channels'):
                    metadata.channels = int(info.channels)
                
                # Bit depth (not always available)
                if hasattr(info, 'bits_per_sample'):
                    metadata.bit_depth = int(info.bits_per_sample)
                
                # Bitrate (for compressed formats)
                if hasattr(info, 'bitrate'):
                    metadata.bitrate = int(info.bitrate)
            
            # Extract only comment tag (for description/notes)
            # Skip music tags (title, artist, album, etc.) to speed up import
            if suffix == '.mp3':
                self._extract_comment_only_id3(audio, metadata)
            elif suffix == '.flac':
                self._extract_comment_only_vorbis(audio, metadata)
            elif suffix == '.ogg':
                self._extract_comment_only_vorbis(audio, metadata)
            elif suffix in ('.m4a', '.mp4'):
                self._extract_comment_only_mp4(audio, metadata)
            elif suffix in ('.wav', '.aiff', '.aif'):
                # WAV and AIFF may have ID3 tags
                if hasattr(audio, 'tags') and audio.tags:
                    self._extract_comment_only_id3(audio, metadata)

            # 仅当需要完整标签时再复制（百万级导入时跳过可显著减少 CPU 与内存）
            if store_raw and hasattr(audio, 'tags') and audio.tags:
                metadata.raw = dict(audio.tags)

        except PermissionError as e:
            logger.warning(f"Permission denied when reading {file_path.name}: {e}")
            return self._extract_fallback(file_path)
        except Exception as e:
            logger.warning(f"Mutagen extraction error for {file_path.name}: {e}")
            return self._extract_fallback(file_path)
        
        return metadata
    
    
    def _extract_comment_only_id3(self, audio, metadata: AudioMetadata) -> None:
        """Extract only comment and original_filename from ID3 tags (MP3, WAV, AIFF) - optimized for speed."""
        tags = audio.tags
        if not tags:
            return
        
        # Comment
        if 'COMM' in tags:
            metadata.comment = str(tags['COMM'])
        
        # Original filename (TXXX frame)
        if hasattr(tags, 'getall'):
            txxx_frames = tags.getall('TXXX')
            for frame in txxx_frames:
                if hasattr(frame, 'desc') and frame.desc == 'ORIGINAL_FILENAME':
                    if hasattr(frame, 'text') and frame.text:
                        metadata.original_filename = str(frame.text[0])
                        break
    
    def _extract_comment_only_vorbis(self, audio, metadata: AudioMetadata) -> None:
        """Extract only comment and original_filename from Vorbis comments (FLAC, OGG) - optimized for speed."""
        tags = audio.tags
        if not tags:
            return
        
        # Comment
        if 'comment' in tags:
            metadata.comment = tags['comment'][0]
        
        # Original filename
        if 'ORIGINAL_FILENAME' in tags:
            metadata.original_filename = tags['ORIGINAL_FILENAME'][0]
        elif 'original_filename' in tags:
            metadata.original_filename = tags['original_filename'][0]
    
    def _extract_comment_only_mp4(self, audio, metadata: AudioMetadata) -> None:
        """Extract only comment and original_filename from MP4/M4A tags - optimized for speed."""
        tags = audio.tags
        if not tags:
            return
        
        # Comment
        if '\xa9cmt' in tags:
            metadata.comment = tags['\xa9cmt'][0]
        
        # Original filename
        if '----:com.apple.iTunes:ORIGINAL_FILENAME' in tags:
            try:
                metadata.original_filename = tags['----:com.apple.iTunes:ORIGINAL_FILENAME'][0].decode('utf-8')
            except:
                pass
    
    def _extract_id3_tags(self, audio, metadata: AudioMetadata) -> None:
        """Extract ID3 tags (MP3, WAV, AIFF)."""
        tags = audio.tags
        if not tags:
            return
        
        # Title
        if 'TIT2' in tags:
            metadata.title = str(tags['TIT2'])
        
        # Artist
        if 'TPE1' in tags:
            metadata.artist = str(tags['TPE1'])
        
        # Album
        if 'TALB' in tags:
            metadata.album = str(tags['TALB'])
        
        # Genre
        if 'TCON' in tags:
            metadata.genre = str(tags['TCON'])
        
        # Year
        if 'TDRC' in tags:
            try:
                metadata.year = int(str(tags['TDRC'])[:4])
            except (ValueError, IndexError):
                pass
        
        # Track number
        if 'TRCK' in tags:
            try:
                track_str = str(tags['TRCK']).split('/')[0]
                metadata.track_number = int(track_str)
            except (ValueError, IndexError):
                pass
        
        # Comment
        if 'COMM' in tags:
            metadata.comment = str(tags['COMM'])
    
    def _extract_vorbis_tags(self, audio, metadata: AudioMetadata) -> None:
        """Extract Vorbis comments (FLAC, OGG)."""
        tags = audio.tags
        if not tags:
            return
        
        # Title
        if 'title' in tags:
            metadata.title = tags['title'][0]
        
        # Artist
        if 'artist' in tags:
            metadata.artist = tags['artist'][0]
        
        # Album
        if 'album' in tags:
            metadata.album = tags['album'][0]
        
        # Genre
        if 'genre' in tags:
            metadata.genre = tags['genre'][0]
        
        # Year/Date
        if 'date' in tags:
            try:
                metadata.year = int(tags['date'][0][:4])
            except (ValueError, IndexError):
                pass
        
        # Track number
        if 'tracknumber' in tags:
            try:
                metadata.track_number = int(tags['tracknumber'][0].split('/')[0])
            except (ValueError, IndexError):
                pass
        
        # Comment
        if 'comment' in tags:
            metadata.comment = tags['comment'][0]
    
    def _extract_mp4_tags(self, audio, metadata: AudioMetadata) -> None:
        """Extract MP4/M4A tags."""
        tags = audio.tags
        if not tags:
            return
        
        # Title
        if '\xa9nam' in tags:
            metadata.title = tags['\xa9nam'][0]
        
        # Artist
        if '\xa9ART' in tags:
            metadata.artist = tags['\xa9ART'][0]
        
        # Album
        if '\xa9alb' in tags:
            metadata.album = tags['\xa9alb'][0]
        
        # Genre
        if '\xa9gen' in tags:
            metadata.genre = tags['\xa9gen'][0]
        
        # Year
        if '\xa9day' in tags:
            try:
                metadata.year = int(tags['\xa9day'][0][:4])
            except (ValueError, IndexError):
                pass
        
        # Track number
        if 'trkn' in tags:
            try:
                metadata.track_number = tags['trkn'][0][0]
            except (IndexError, TypeError):
                pass
        
        # Comment
        if '\xa9cmt' in tags:
            metadata.comment = tags['\xa9cmt'][0]
    
    def _extract_fallback(self, file_path: Path) -> AudioMetadata:
        """
        Fallback metadata extraction without Mutagen.
        
        Only extracts basic file information.
        """
        metadata = AudioMetadata()
        metadata.format = file_path.suffix.lstrip('.').lower()
        
        # Try to get file size for rough duration estimate
        try:
            file_size = file_path.stat().st_size
            
            # Very rough estimate based on format
            if metadata.format == 'wav':
                # Assume 16-bit stereo 44.1kHz
                bytes_per_second = 44100 * 2 * 2
                metadata.duration = file_size / bytes_per_second
                metadata.sample_rate = 44100
                metadata.bit_depth = 16
                metadata.channels = 2
            elif metadata.format == 'mp3':
                # Assume 128kbps
                metadata.duration = file_size / (128 * 1000 / 8)
                metadata.bitrate = 128
                
        except Exception as e:
            logger.debug(f"Fallback extraction error: {e}")
        
        return metadata


# Global extractor instance
_extractor: Optional[MetadataExtractor] = None


def get_metadata_extractor() -> MetadataExtractor:
    """Get the global metadata extractor."""
    global _extractor
    if _extractor is None:
        _extractor = MetadataExtractor()
    return _extractor


def extract_metadata(file_path: Path) -> Optional[AudioMetadata]:
    """
    Extract metadata from an audio file.
    
    Args:
        file_path: Path to the audio file
        
    Returns:
        AudioMetadata: Extracted metadata
    """
    return get_metadata_extractor().extract(file_path)


def extract_one_for_pool(args: tuple) -> tuple:
    """
    供 multiprocessing.Pool 调用的可 pickle 函数：(idx, path_str) -> (idx, path_str, metadata_or_none)。
    子进程内创建 MetadataExtractor，避免跨进程传递复杂对象。
    """
    idx, path_str = args
    try:
        extractor = MetadataExtractor()
        meta = extractor.extract(Path(path_str))
        return (idx, path_str, meta)
    except Exception:
        return (idx, path_str, None)
