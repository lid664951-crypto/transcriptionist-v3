"""
Project Exporter

Handles exporting projects with file copying and metadata generation.
"""

import asyncio
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any

from ...domain.models.project import Project
from ...domain.models.audio_file import AudioFile

logger = logging.getLogger(__name__)


class ExportFormat(Enum):
    """Export format options."""
    FLAT = "flat"           # All files in one directory
    BY_CATEGORY = "category"  # Organized by UCS category
    BY_DATE = "date"        # Organized by date
    CUSTOM = "custom"       # Custom structure


class NamingScheme(Enum):
    """File naming scheme options."""
    ORIGINAL = "original"   # Keep original names
    UCS = "ucs"            # Use UCS naming
    SEQUENTIAL = "sequential"  # Sequential numbering
    CUSTOM = "custom"      # Custom pattern


@dataclass
class ExportOptions:
    """Options for project export."""
    
    # Output settings
    output_dir: Path = field(default_factory=Path)
    format: ExportFormat = ExportFormat.FLAT
    naming_scheme: NamingScheme = NamingScheme.ORIGINAL
    custom_pattern: str = ""
    
    # File handling
    copy_files: bool = True
    create_symlinks: bool = False
    overwrite_existing: bool = False
    
    # Metadata
    include_metadata: bool = True
    metadata_format: str = "json"  # json, csv, xml
    include_project_info: bool = True
    
    # Audio processing
    convert_format: Optional[str] = None  # wav, mp3, flac, etc.
    normalize_loudness: bool = False
    target_loudness: float = -23.0  # LUFS
    
    # Progress
    progress_callback: Optional[Callable[[float, str], None]] = None


@dataclass
class ExportResult:
    """Result of an export operation."""
    
    success: bool = False
    output_dir: Optional[Path] = None
    files_exported: int = 0
    files_failed: int = 0
    total_size: int = 0
    duration_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'success': self.success,
            'output_dir': str(self.output_dir) if self.output_dir else None,
            'files_exported': self.files_exported,
            'files_failed': self.files_failed,
            'total_size': self.total_size,
            'duration_seconds': self.duration_seconds,
            'errors': self.errors,
            'warnings': self.warnings,
        }


class ProjectExporter:
    """
    Exports projects with file copying and metadata generation.
    
    Features:
    - Copy files to export directory
    - Generate metadata sidecar files
    - Support multiple export formats
    - Progress tracking
    - Error handling
    """
    
    def __init__(self, library=None):
        """
        Initialize the exporter.
        
        Args:
            library: Audio file library for file lookups
        """
        self.library = library
        self._cancelled = False
    
    def cancel(self) -> None:
        """Cancel the current export operation."""
        self._cancelled = True
    
    async def export_project(
        self,
        project: Project,
        files: List[AudioFile],
        options: ExportOptions,
    ) -> ExportResult:
        """
        Export a project.
        
        Args:
            project: Project to export
            files: List of audio files in the project
            options: Export options
        
        Returns:
            ExportResult with details
        """
        self._cancelled = False
        start_time = datetime.now()
        result = ExportResult()
        
        try:
            # Create output directory
            output_dir = self._prepare_output_dir(project, options)
            result.output_dir = output_dir
            
            # Export files
            total = len(files)
            for i, audio_file in enumerate(files):
                if self._cancelled:
                    result.warnings.append("Export cancelled by user")
                    break
                
                # Update progress
                progress = (i + 1) / total
                if options.progress_callback:
                    options.progress_callback(
                        progress,
                        f"Exporting {audio_file.filename}..."
                    )
                
                try:
                    exported_path = await self._export_file(
                        audio_file, output_dir, options, i + 1
                    )
                    if exported_path:
                        result.files_exported += 1
                        result.total_size += audio_file.file_size or 0
                        
                        # Generate metadata sidecar
                        if options.include_metadata:
                            await self._write_metadata_sidecar(
                                audio_file, exported_path, options
                            )
                except Exception as e:
                    result.files_failed += 1
                    result.errors.append(f"{audio_file.filename}: {e}")
                    logger.error(f"Failed to export {audio_file.filename}: {e}")
            
            # Write project info
            if options.include_project_info:
                await self._write_project_info(project, files, output_dir, options)
            
            result.success = result.files_failed == 0
            
        except Exception as e:
            result.success = False
            result.errors.append(str(e))
            logger.error(f"Export failed: {e}")
        
        finally:
            result.duration_seconds = (datetime.now() - start_time).total_seconds()
        
        return result
    
    def _prepare_output_dir(
        self,
        project: Project,
        options: ExportOptions,
    ) -> Path:
        """Prepare the output directory."""
        # Create project subdirectory
        safe_name = self._sanitize_dirname(project.name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dir_name = f"{safe_name}_{timestamp}"
        
        output_dir = options.output_dir / dir_name
        output_dir.mkdir(parents=True, exist_ok=True)
        
        return output_dir
    
    def _sanitize_dirname(self, name: str) -> str:
        """Sanitize a string for use as a directory name."""
        invalid_chars = '<>:"/\\|?*'
        result = name
        for char in invalid_chars:
            result = result.replace(char, '_')
        return result.strip() or 'project'
    
    async def _export_file(
        self,
        audio_file: AudioFile,
        output_dir: Path,
        options: ExportOptions,
        index: int,
    ) -> Optional[Path]:
        """Export a single file."""
        source_path = Path(audio_file.file_path)
        
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")
        
        # Determine destination path
        dest_name = self._get_export_filename(audio_file, options, index)
        
        # Handle format-based subdirectories
        if options.format == ExportFormat.BY_CATEGORY:
            category = audio_file.metadata.get('category', 'Uncategorized') if audio_file.metadata else 'Uncategorized'
            subdir = output_dir / self._sanitize_dirname(category)
            subdir.mkdir(exist_ok=True)
            dest_path = subdir / dest_name
        elif options.format == ExportFormat.BY_DATE:
            date_str = datetime.now().strftime("%Y-%m-%d")
            subdir = output_dir / date_str
            subdir.mkdir(exist_ok=True)
            dest_path = subdir / dest_name
        else:
            dest_path = output_dir / dest_name
        
        # Handle existing files
        if dest_path.exists() and not options.overwrite_existing:
            dest_path = self._get_unique_path(dest_path)
        
        # Copy or link file
        if options.create_symlinks:
            os.symlink(source_path, dest_path)
        elif options.copy_files:
            # Use asyncio to avoid blocking
            await asyncio.to_thread(shutil.copy2, source_path, dest_path)
        
        return dest_path
    
    def _get_export_filename(
        self,
        audio_file: AudioFile,
        options: ExportOptions,
        index: int,
    ) -> str:
        """Get the export filename based on naming scheme."""
        ext = Path(audio_file.filename).suffix
        
        if options.naming_scheme == NamingScheme.ORIGINAL:
            return audio_file.filename
        
        elif options.naming_scheme == NamingScheme.SEQUENTIAL:
            return f"{index:04d}{ext}"
        
        elif options.naming_scheme == NamingScheme.UCS:
            # Use UCS name if available
            if audio_file.metadata and audio_file.metadata.get('ucs_name'):
                return audio_file.metadata['ucs_name'] + ext
            return audio_file.filename
        
        elif options.naming_scheme == NamingScheme.CUSTOM:
            # Apply custom pattern
            return self._apply_naming_pattern(
                audio_file, options.custom_pattern, index
            ) + ext
        
        return audio_file.filename
    
    def _apply_naming_pattern(
        self,
        audio_file: AudioFile,
        pattern: str,
        index: int,
    ) -> str:
        """Apply a custom naming pattern."""
        # Available placeholders:
        # {name} - original filename without extension
        # {index} - sequential index
        # {category} - UCS category
        # {subcategory} - UCS subcategory
        # {date} - current date
        
        name = Path(audio_file.filename).stem
        metadata = audio_file.metadata or {}
        
        result = pattern
        result = result.replace('{name}', name)
        result = result.replace('{index}', f"{index:04d}")
        result = result.replace('{category}', metadata.get('category', 'SFX'))
        result = result.replace('{subcategory}', metadata.get('subcategory', ''))
        result = result.replace('{date}', datetime.now().strftime("%Y%m%d"))
        
        return self._sanitize_dirname(result)
    
    def _get_unique_path(self, path: Path) -> Path:
        """Get a unique path by adding a number suffix."""
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
                raise RuntimeError("Too many filename conflicts")
    
    async def _write_metadata_sidecar(
        self,
        audio_file: AudioFile,
        exported_path: Path,
        options: ExportOptions,
    ) -> None:
        """Write metadata sidecar file."""
        if options.metadata_format == 'json':
            sidecar_path = exported_path.with_suffix(exported_path.suffix + '.json')
            metadata = self._build_metadata_dict(audio_file)
            
            async def write_json():
                with open(sidecar_path, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            await asyncio.to_thread(write_json)
    
    def _build_metadata_dict(self, audio_file: AudioFile) -> Dict[str, Any]:
        """Build metadata dictionary for export."""
        metadata = {
            'filename': audio_file.filename,
            'original_path': audio_file.file_path,
            'duration': audio_file.duration,
            'sample_rate': audio_file.sample_rate,
            'channels': audio_file.channels,
            'bit_depth': audio_file.bit_depth,
            'file_size': audio_file.file_size,
            'format': audio_file.format,
            'exported_at': datetime.now().isoformat(),
        }
        
        # Add custom metadata
        if audio_file.metadata:
            metadata['custom'] = audio_file.metadata
        
        return metadata
    
    async def _write_project_info(
        self,
        project: Project,
        files: List[AudioFile],
        output_dir: Path,
        options: ExportOptions,
    ) -> None:
        """Write project information file."""
        info = {
            'project': {
                'name': project.name,
                'description': project.description,
                'template': project.template_name,
                'created_at': project.created_at.isoformat() if project.created_at else None,
                'exported_at': datetime.now().isoformat(),
            },
            'files': {
                'count': len(files),
                'total_duration': sum(f.duration or 0 for f in files),
                'total_size': sum(f.file_size or 0 for f in files),
            },
            'export_options': {
                'format': options.format.value,
                'naming_scheme': options.naming_scheme.value,
                'include_metadata': options.include_metadata,
            },
        }
        
        info_path = output_dir / 'project_info.json'
        
        async def write_info():
            with open(info_path, 'w', encoding='utf-8') as f:
                json.dump(info, f, ensure_ascii=False, indent=2)
        
        await asyncio.to_thread(write_info)
        
        # Also write a simple file list
        list_path = output_dir / 'file_list.txt'
        
        async def write_list():
            with open(list_path, 'w', encoding='utf-8') as f:
                f.write(f"# {project.name}\n")
                f.write(f"# Exported: {datetime.now().isoformat()}\n")
                f.write(f"# Files: {len(files)}\n\n")
                for audio_file in files:
                    f.write(f"{audio_file.filename}\n")
        
        await asyncio.to_thread(write_list)
