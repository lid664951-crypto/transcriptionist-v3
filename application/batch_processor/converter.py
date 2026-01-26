"""
Format Converter

Audio format conversion using ffmpeg.
"""

import asyncio
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class AudioFormat(Enum):
    """Supported audio formats."""
    WAV = "wav"
    FLAC = "flac"
    MP3 = "mp3"
    OGG = "ogg"
    AIFF = "aiff"
    M4A = "m4a"
    OPUS = "opus"


class AudioCodec(Enum):
    """Audio codecs for encoding."""
    PCM_S16LE = "pcm_s16le"  # WAV 16-bit
    PCM_S24LE = "pcm_s24le"  # WAV 24-bit
    PCM_S32LE = "pcm_s32le"  # WAV 32-bit
    FLAC = "flac"
    LIBMP3LAME = "libmp3lame"
    LIBVORBIS = "libvorbis"
    AAC = "aac"
    LIBOPUS = "libopus"


@dataclass
class ConversionOptions:
    """Options for audio format conversion."""
    
    # Output format
    output_format: AudioFormat = AudioFormat.WAV
    codec: Optional[AudioCodec] = None
    
    # Audio settings
    sample_rate: Optional[int] = None  # None = keep original
    channels: Optional[int] = None  # None = keep original
    bit_depth: Optional[int] = None  # 16, 24, 32
    
    # Quality settings (for lossy formats)
    bitrate: Optional[str] = None  # e.g., "320k", "192k"
    quality: Optional[int] = None  # VBR quality (0-9 for MP3)
    
    # Output path
    output_dir: Optional[Path] = None
    preserve_structure: bool = False
    overwrite: bool = False
    
    # Metadata
    copy_metadata: bool = True
    
    def get_codec(self) -> str:
        """Get the codec string for ffmpeg."""
        if self.codec:
            return self.codec.value
        
        # Default codecs for each format
        codec_map = {
            AudioFormat.WAV: AudioCodec.PCM_S16LE,
            AudioFormat.FLAC: AudioCodec.FLAC,
            AudioFormat.MP3: AudioCodec.LIBMP3LAME,
            AudioFormat.OGG: AudioCodec.LIBVORBIS,
            AudioFormat.M4A: AudioCodec.AAC,
            AudioFormat.OPUS: AudioCodec.LIBOPUS,
            AudioFormat.AIFF: AudioCodec.PCM_S16LE,
        }
        return codec_map.get(self.output_format, AudioCodec.PCM_S16LE).value


@dataclass
class ConversionResult:
    """Result of a conversion operation."""
    
    success: bool = False
    input_path: Optional[Path] = None
    output_path: Optional[Path] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0
    input_size: int = 0
    output_size: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'success': self.success,
            'input_path': str(self.input_path) if self.input_path else None,
            'output_path': str(self.output_path) if self.output_path else None,
            'error': self.error,
            'duration_seconds': self.duration_seconds,
            'input_size': self.input_size,
            'output_size': self.output_size,
        }


class FormatConverter:
    """
    Audio format converter using ffmpeg.
    
    Features:
    - Convert between common audio formats
    - Adjust sample rate, channels, bit depth
    - Quality settings for lossy formats
    - Metadata preservation
    - Progress tracking
    """
    
    def __init__(self, ffmpeg_path: Optional[str] = None):
        """
        Initialize the converter.
        
        Args:
            ffmpeg_path: Path to ffmpeg executable (auto-detect if None)
        """
        self.ffmpeg_path = ffmpeg_path or self._find_ffmpeg()
        self._cancelled = False
    
    def _find_ffmpeg(self) -> str:
        """Find ffmpeg executable."""
        # Try common locations
        ffmpeg = shutil.which('ffmpeg')
        if ffmpeg:
            return ffmpeg
        
        # Windows common paths
        common_paths = [
            r'C:\ffmpeg\bin\ffmpeg.exe',
            r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
        ]
        for path in common_paths:
            if Path(path).exists():
                return path
        
        return 'ffmpeg'  # Hope it's in PATH
    
    def is_available(self) -> bool:
        """Check if ffmpeg is available."""
        try:
            result = subprocess.run(
                [self.ffmpeg_path, '-version'],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def cancel(self) -> None:
        """Cancel the current operation."""
        self._cancelled = True
    
    async def convert(
        self,
        input_path: Path,
        options: ConversionOptions,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> ConversionResult:
        """
        Convert a single audio file.
        
        Args:
            input_path: Path to input file
            options: Conversion options
            progress_callback: Progress callback (progress, message)
        
        Returns:
            ConversionResult
        """
        import time
        start_time = time.time()
        
        result = ConversionResult(input_path=input_path)
        result.input_size = input_path.stat().st_size if input_path.exists() else 0
        
        try:
            # Determine output path
            output_path = self._get_output_path(input_path, options)
            result.output_path = output_path
            
            # Check if output exists
            if output_path.exists() and not options.overwrite:
                result.error = "Output file already exists"
                return result
            
            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Build ffmpeg command
            cmd = self._build_command(input_path, output_path, options)
            
            if progress_callback:
                progress_callback(0.0, f"Converting {input_path.name}...")
            
            # Run conversion
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await process.communicate()
            
            if self._cancelled:
                result.error = "Cancelled"
                if output_path.exists():
                    output_path.unlink()
                return result
            
            if process.returncode != 0:
                result.error = stderr.decode('utf-8', errors='replace')
                logger.error(f"FFmpeg error: {result.error}")
                return result
            
            result.success = True
            result.output_size = output_path.stat().st_size if output_path.exists() else 0
            
            if progress_callback:
                progress_callback(1.0, f"Converted {input_path.name}")
            
        except Exception as e:
            result.error = str(e)
            logger.error(f"Conversion error: {e}")
        
        finally:
            result.duration_seconds = time.time() - start_time
        
        return result
    
    async def convert_batch(
        self,
        input_paths: List[Path],
        options: ConversionOptions,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> List[ConversionResult]:
        """
        Convert multiple audio files.
        
        Args:
            input_paths: List of input file paths
            options: Conversion options
            progress_callback: Progress callback
        
        Returns:
            List of ConversionResults
        """
        self._cancelled = False
        results = []
        total = len(input_paths)
        
        for i, input_path in enumerate(input_paths):
            if self._cancelled:
                break
            
            def file_progress(progress: float, message: str):
                overall = (i + progress) / total
                if progress_callback:
                    progress_callback(overall, message)
            
            result = await self.convert(input_path, options, file_progress)
            results.append(result)
        
        return results
    
    def _get_output_path(self, input_path: Path, options: ConversionOptions) -> Path:
        """Determine the output path for a file."""
        # Get output directory
        if options.output_dir:
            output_dir = options.output_dir
        else:
            output_dir = input_path.parent
        
        # Build output filename
        stem = input_path.stem
        ext = f".{options.output_format.value}"
        output_name = f"{stem}{ext}"
        
        return output_dir / output_name
    
    def _build_command(
        self,
        input_path: Path,
        output_path: Path,
        options: ConversionOptions,
    ) -> List[str]:
        """Build the ffmpeg command."""
        cmd = [
            self.ffmpeg_path,
            '-y' if options.overwrite else '-n',
            '-i', str(input_path),
        ]
        
        # Audio codec
        cmd.extend(['-c:a', options.get_codec()])
        
        # Sample rate
        if options.sample_rate:
            cmd.extend(['-ar', str(options.sample_rate)])
        
        # Channels
        if options.channels:
            cmd.extend(['-ac', str(options.channels)])
        
        # Bitrate (for lossy formats)
        if options.bitrate:
            cmd.extend(['-b:a', options.bitrate])
        
        # Quality (for VBR)
        if options.quality is not None:
            if options.output_format == AudioFormat.MP3:
                cmd.extend(['-q:a', str(options.quality)])
            elif options.output_format == AudioFormat.OGG:
                cmd.extend(['-q:a', str(options.quality)])
        
        # Metadata handling
        if not options.copy_metadata:
            cmd.extend(['-map_metadata', '-1'])
        
        # Output file
        cmd.append(str(output_path))
        
        return cmd
    
    def get_supported_formats(self) -> List[AudioFormat]:
        """Get list of supported output formats."""
        return list(AudioFormat)
    
    def get_format_info(self, format: AudioFormat) -> Dict[str, Any]:
        """Get information about a format."""
        info = {
            AudioFormat.WAV: {
                'name': 'WAV',
                'description': 'Uncompressed PCM audio',
                'lossy': False,
                'supports_bitrate': False,
                'supports_quality': False,
                'default_extension': '.wav',
            },
            AudioFormat.FLAC: {
                'name': 'FLAC',
                'description': 'Free Lossless Audio Codec',
                'lossy': False,
                'supports_bitrate': False,
                'supports_quality': True,
                'default_extension': '.flac',
            },
            AudioFormat.MP3: {
                'name': 'MP3',
                'description': 'MPEG Audio Layer III',
                'lossy': True,
                'supports_bitrate': True,
                'supports_quality': True,
                'default_extension': '.mp3',
            },
            AudioFormat.OGG: {
                'name': 'OGG Vorbis',
                'description': 'Ogg Vorbis audio',
                'lossy': True,
                'supports_bitrate': True,
                'supports_quality': True,
                'default_extension': '.ogg',
            },
            AudioFormat.M4A: {
                'name': 'M4A/AAC',
                'description': 'MPEG-4 Audio',
                'lossy': True,
                'supports_bitrate': True,
                'supports_quality': False,
                'default_extension': '.m4a',
            },
            AudioFormat.AIFF: {
                'name': 'AIFF',
                'description': 'Audio Interchange File Format',
                'lossy': False,
                'supports_bitrate': False,
                'supports_quality': False,
                'default_extension': '.aiff',
            },
            AudioFormat.OPUS: {
                'name': 'Opus',
                'description': 'Opus audio codec',
                'lossy': True,
                'supports_bitrate': True,
                'supports_quality': False,
                'default_extension': '.opus',
            },
        }
        return info.get(format, {})
