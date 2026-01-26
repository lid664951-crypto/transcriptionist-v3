"""
Loudness Normalizer

Audio loudness normalization using pyloudnorm and soundfile.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class NormalizationStandard(Enum):
    """Loudness normalization standards."""
    EBU_R128 = "ebu_r128"  # -23 LUFS (broadcast)
    ATSC_A85 = "atsc_a85"  # -24 LKFS (US broadcast)
    STREAMING = "streaming"  # -14 LUFS (Spotify, YouTube)
    CUSTOM = "custom"


@dataclass
class NormalizationOptions:
    """Options for loudness normalization."""
    
    # Target loudness
    standard: NormalizationStandard = NormalizationStandard.EBU_R128
    target_loudness: float = -23.0  # LUFS
    
    # Peak limiting
    peak_limit: float = -1.0  # dBTP (True Peak)
    apply_limiter: bool = True
    
    # Output settings
    output_dir: Optional[Path] = None
    suffix: str = "_normalized"
    overwrite: bool = False
    
    # Analysis
    block_size: float = 0.4  # seconds
    
    def get_target_loudness(self) -> float:
        """Get target loudness based on standard."""
        if self.standard == NormalizationStandard.CUSTOM:
            return self.target_loudness
        
        targets = {
            NormalizationStandard.EBU_R128: -23.0,
            NormalizationStandard.ATSC_A85: -24.0,
            NormalizationStandard.STREAMING: -14.0,
        }
        return targets.get(self.standard, -23.0)


@dataclass
class LoudnessAnalysis:
    """Loudness analysis results."""
    
    integrated_loudness: float = 0.0  # LUFS
    loudness_range: float = 0.0  # LU
    true_peak: float = 0.0  # dBTP
    short_term_max: float = 0.0  # LUFS
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'integrated_loudness': self.integrated_loudness,
            'loudness_range': self.loudness_range,
            'true_peak': self.true_peak,
            'short_term_max': self.short_term_max,
        }


@dataclass
class NormalizationResult:
    """Result of a normalization operation."""
    
    success: bool = False
    input_path: Optional[Path] = None
    output_path: Optional[Path] = None
    error: Optional[str] = None
    
    # Analysis
    original_loudness: Optional[LoudnessAnalysis] = None
    normalized_loudness: Optional[LoudnessAnalysis] = None
    gain_applied: float = 0.0  # dB
    
    # Timing
    duration_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'success': self.success,
            'input_path': str(self.input_path) if self.input_path else None,
            'output_path': str(self.output_path) if self.output_path else None,
            'error': self.error,
            'original_loudness': self.original_loudness.to_dict() if self.original_loudness else None,
            'normalized_loudness': self.normalized_loudness.to_dict() if self.normalized_loudness else None,
            'gain_applied': self.gain_applied,
            'duration_seconds': self.duration_seconds,
        }


class LoudnessNormalizer:
    """
    Audio loudness normalizer using pyloudnorm.
    
    Features:
    - EBU R128 loudness measurement
    - Integrated loudness normalization
    - True peak limiting
    - Multiple standard presets
    - Batch processing
    """
    
    def __init__(self):
        """Initialize the normalizer."""
        self._cancelled = False
        self._meter = None
    
    def _get_meter(self, sample_rate: int):
        """Get or create a loudness meter."""
        try:
            import pyloudnorm as pyln
            return pyln.Meter(sample_rate, block_size=0.4)
        except ImportError:
            logger.warning("pyloudnorm not available, using fallback")
            return None
    
    def is_available(self) -> bool:
        """Check if pyloudnorm is available."""
        try:
            import pyloudnorm
            import soundfile
            return True
        except ImportError:
            return False
    
    def cancel(self) -> None:
        """Cancel the current operation."""
        self._cancelled = True
    
    async def analyze(
        self,
        input_path: Path,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> LoudnessAnalysis:
        """
        Analyze the loudness of an audio file.
        
        Args:
            input_path: Path to audio file
            progress_callback: Progress callback
        
        Returns:
            LoudnessAnalysis
        """
        try:
            import soundfile as sf
            import pyloudnorm as pyln
        except ImportError:
            raise RuntimeError("pyloudnorm and soundfile are required")
        
        if progress_callback:
            progress_callback(0.0, f"Analyzing {input_path.name}...")
        
        # Read audio file
        data, sample_rate = await asyncio.to_thread(sf.read, str(input_path))
        
        if progress_callback:
            progress_callback(0.3, "Measuring loudness...")
        
        # Create meter
        meter = pyln.Meter(sample_rate)
        
        # Measure integrated loudness
        integrated = meter.integrated_loudness(data)
        
        if progress_callback:
            progress_callback(0.6, "Calculating true peak...")
        
        # Calculate true peak
        true_peak = self._calculate_true_peak(data)
        
        # Calculate loudness range (simplified)
        loudness_range = self._calculate_loudness_range(data, sample_rate, meter)
        
        if progress_callback:
            progress_callback(1.0, "Analysis complete")
        
        return LoudnessAnalysis(
            integrated_loudness=integrated,
            loudness_range=loudness_range,
            true_peak=true_peak,
            short_term_max=integrated + 3.0,  # Approximation
        )
    
    async def normalize(
        self,
        input_path: Path,
        options: NormalizationOptions,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> NormalizationResult:
        """
        Normalize the loudness of an audio file.
        
        Args:
            input_path: Path to input file
            options: Normalization options
            progress_callback: Progress callback
        
        Returns:
            NormalizationResult
        """
        import time
        start_time = time.time()
        
        result = NormalizationResult(input_path=input_path)
        
        try:
            import soundfile as sf
            import pyloudnorm as pyln
        except ImportError:
            result.error = "pyloudnorm and soundfile are required"
            return result
        
        try:
            # Determine output path
            output_path = self._get_output_path(input_path, options)
            result.output_path = output_path
            
            # Check if output exists
            if output_path.exists() and not options.overwrite:
                result.error = "Output file already exists"
                return result
            
            if progress_callback:
                progress_callback(0.0, f"Reading {input_path.name}...")
            
            # Read audio file
            data, sample_rate = await asyncio.to_thread(sf.read, str(input_path))
            
            if self._cancelled:
                result.error = "Cancelled"
                return result
            
            if progress_callback:
                progress_callback(0.2, "Analyzing loudness...")
            
            # Create meter
            meter = pyln.Meter(sample_rate)
            
            # Measure original loudness
            original_loudness = meter.integrated_loudness(data)
            result.original_loudness = LoudnessAnalysis(
                integrated_loudness=original_loudness,
                true_peak=self._calculate_true_peak(data),
            )
            
            if progress_callback:
                progress_callback(0.4, "Normalizing...")
            
            # Calculate gain
            target = options.get_target_loudness()
            gain_db = target - original_loudness
            result.gain_applied = gain_db
            
            # Apply gain
            gain_linear = 10 ** (gain_db / 20.0)
            normalized_data = data * gain_linear
            
            if progress_callback:
                progress_callback(0.6, "Applying peak limiter...")
            
            # Apply peak limiter if needed
            if options.apply_limiter:
                normalized_data = self._apply_limiter(
                    normalized_data, options.peak_limit
                )
            
            if self._cancelled:
                result.error = "Cancelled"
                return result
            
            if progress_callback:
                progress_callback(0.8, "Writing output...")
            
            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write output file
            await asyncio.to_thread(
                sf.write, str(output_path), normalized_data, sample_rate
            )
            
            # Measure normalized loudness
            normalized_loudness = meter.integrated_loudness(normalized_data)
            result.normalized_loudness = LoudnessAnalysis(
                integrated_loudness=normalized_loudness,
                true_peak=self._calculate_true_peak(normalized_data),
            )
            
            result.success = True
            
            if progress_callback:
                progress_callback(1.0, f"Normalized {input_path.name}")
            
        except Exception as e:
            result.error = str(e)
            logger.error(f"Normalization error: {e}")
        
        finally:
            result.duration_seconds = time.time() - start_time
        
        return result
    
    async def normalize_batch(
        self,
        input_paths: List[Path],
        options: NormalizationOptions,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> List[NormalizationResult]:
        """
        Normalize multiple audio files.
        
        Args:
            input_paths: List of input file paths
            options: Normalization options
            progress_callback: Progress callback
        
        Returns:
            List of NormalizationResults
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
            
            result = await self.normalize(input_path, options, file_progress)
            results.append(result)
        
        return results
    
    def _get_output_path(self, input_path: Path, options: NormalizationOptions) -> Path:
        """Determine the output path for a file."""
        if options.output_dir:
            output_dir = options.output_dir
        else:
            output_dir = input_path.parent
        
        stem = input_path.stem
        suffix = input_path.suffix
        output_name = f"{stem}{options.suffix}{suffix}"
        
        return output_dir / output_name
    
    def _calculate_true_peak(self, data: np.ndarray) -> float:
        """Calculate true peak in dBTP."""
        # Simple peak calculation (true peak would require oversampling)
        peak = np.max(np.abs(data))
        if peak > 0:
            return 20 * np.log10(peak)
        return -np.inf
    
    def _calculate_loudness_range(
        self,
        data: np.ndarray,
        sample_rate: int,
        meter,
    ) -> float:
        """Calculate loudness range (simplified)."""
        # This is a simplified calculation
        # Full LRA requires short-term loudness measurements
        block_size = int(3.0 * sample_rate)  # 3 second blocks
        
        if len(data.shape) == 1:
            data = data.reshape(-1, 1)
        
        loudness_values = []
        for i in range(0, len(data) - block_size, block_size // 2):
            block = data[i:i + block_size]
            try:
                loudness = meter.integrated_loudness(block)
                if not np.isinf(loudness):
                    loudness_values.append(loudness)
            except Exception:
                pass
        
        if len(loudness_values) < 2:
            return 0.0
        
        # LRA is approximately the difference between 95th and 10th percentile
        sorted_values = sorted(loudness_values)
        low_idx = int(len(sorted_values) * 0.1)
        high_idx = int(len(sorted_values) * 0.95)
        
        return sorted_values[high_idx] - sorted_values[low_idx]
    
    def _apply_limiter(self, data: np.ndarray, threshold_db: float) -> np.ndarray:
        """Apply a simple peak limiter."""
        threshold_linear = 10 ** (threshold_db / 20.0)
        
        # Find peaks above threshold
        peak = np.max(np.abs(data))
        
        if peak > threshold_linear:
            # Simple limiting by scaling
            scale = threshold_linear / peak
            return data * scale
        
        return data
    
    def get_standard_info(self, standard: NormalizationStandard) -> Dict[str, Any]:
        """Get information about a normalization standard."""
        info = {
            NormalizationStandard.EBU_R128: {
                'name': 'EBU R128',
                'description': 'European broadcast standard',
                'target_loudness': -23.0,
                'peak_limit': -1.0,
                'use_case': 'Broadcast, TV, Radio',
            },
            NormalizationStandard.ATSC_A85: {
                'name': 'ATSC A/85',
                'description': 'US broadcast standard',
                'target_loudness': -24.0,
                'peak_limit': -2.0,
                'use_case': 'US Television',
            },
            NormalizationStandard.STREAMING: {
                'name': 'Streaming',
                'description': 'Streaming platform standard',
                'target_loudness': -14.0,
                'peak_limit': -1.0,
                'use_case': 'Spotify, YouTube, Apple Music',
            },
            NormalizationStandard.CUSTOM: {
                'name': 'Custom',
                'description': 'User-defined target',
                'target_loudness': None,
                'peak_limit': None,
                'use_case': 'Custom requirements',
            },
        }
        return info.get(standard, {})
