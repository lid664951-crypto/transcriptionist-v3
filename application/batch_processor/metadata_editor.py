"""
Batch Metadata Editor

Batch editing of audio file metadata with undo support.
"""

import asyncio
import copy
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class MetadataField(Enum):
    """Common metadata fields."""
    TITLE = "title"
    ARTIST = "artist"
    ALBUM = "album"
    GENRE = "genre"
    YEAR = "year"
    TRACK_NUMBER = "tracknumber"
    COMMENT = "comment"
    DESCRIPTION = "description"
    COPYRIGHT = "copyright"
    
    # UCS-specific fields
    CATEGORY = "category"
    SUBCATEGORY = "subcategory"
    FX_NAME = "fx_name"
    CREATOR_ID = "creator_id"
    SOURCE_ID = "source_id"


class OperationType(Enum):
    """Types of metadata operations."""
    SET = "set"  # Set field to value
    APPEND = "append"  # Append to existing value
    PREPEND = "prepend"  # Prepend to existing value
    REPLACE = "replace"  # Find and replace in value
    CLEAR = "clear"  # Clear field
    COPY = "copy"  # Copy from another field
    FORMAT = "format"  # Apply format pattern


@dataclass
class MetadataOperation:
    """A single metadata operation."""
    
    operation: OperationType = OperationType.SET
    field: Union[MetadataField, str] = MetadataField.TITLE
    value: Any = None
    
    # For replace operation
    find: str = ""
    replace_with: str = ""
    
    # For copy operation
    source_field: Optional[Union[MetadataField, str]] = None
    
    # For format operation
    format_pattern: str = ""
    
    def get_field_name(self) -> str:
        """Get the field name as string."""
        if isinstance(self.field, MetadataField):
            return self.field.value
        return self.field


@dataclass
class MetadataSnapshot:
    """Snapshot of metadata for undo support."""
    
    file_path: Path = field(default_factory=Path)
    timestamp: datetime = field(default_factory=datetime.now)
    original_metadata: Dict[str, Any] = field(default_factory=dict)
    modified_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MetadataEditResult:
    """Result of a metadata edit operation."""
    
    success: bool = False
    file_path: Optional[Path] = None
    error: Optional[str] = None
    fields_modified: List[str] = field(default_factory=list)
    snapshot: Optional[MetadataSnapshot] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'success': self.success,
            'file_path': str(self.file_path) if self.file_path else None,
            'error': self.error,
            'fields_modified': self.fields_modified,
        }


class BatchMetadataEditor:
    """
    Batch metadata editor with undo support.
    
    Features:
    - Multiple operation types (set, append, replace, etc.)
    - Batch processing
    - Undo/redo support via snapshots
    - Progress tracking
    """
    
    def __init__(self, max_undo_history: int = 100):
        """
        Initialize the editor.
        
        Args:
            max_undo_history: Maximum number of undo snapshots to keep
        """
        self.max_undo_history = max_undo_history
        self._undo_stack: List[List[MetadataSnapshot]] = []
        self._redo_stack: List[List[MetadataSnapshot]] = []
        self._cancelled = False
    
    def cancel(self) -> None:
        """Cancel the current operation."""
        self._cancelled = True
    
    async def edit(
        self,
        file_path: Path,
        operations: List[MetadataOperation],
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> MetadataEditResult:
        """
        Edit metadata of a single file.
        
        Args:
            file_path: Path to audio file
            operations: List of operations to apply
            progress_callback: Progress callback
        
        Returns:
            MetadataEditResult
        """
        result = MetadataEditResult(file_path=file_path)
        
        try:
            if progress_callback:
                progress_callback(0.0, f"Reading {file_path.name}...")
            
            # Read current metadata
            original_metadata = await self._read_metadata(file_path)
            
            # Create snapshot for undo
            snapshot = MetadataSnapshot(
                file_path=file_path,
                original_metadata=copy.deepcopy(original_metadata),
            )
            
            if progress_callback:
                progress_callback(0.3, "Applying operations...")
            
            # Apply operations
            modified_metadata = copy.deepcopy(original_metadata)
            for op in operations:
                field_name = op.get_field_name()
                modified_metadata = self._apply_operation(
                    modified_metadata, op
                )
                if field_name not in result.fields_modified:
                    result.fields_modified.append(field_name)
            
            if self._cancelled:
                result.error = "Cancelled"
                return result
            
            if progress_callback:
                progress_callback(0.6, "Writing metadata...")
            
            # Write modified metadata
            await self._write_metadata(file_path, modified_metadata)
            
            # Complete snapshot
            snapshot.modified_metadata = modified_metadata
            result.snapshot = snapshot
            result.success = True
            
            if progress_callback:
                progress_callback(1.0, f"Updated {file_path.name}")
            
        except Exception as e:
            result.error = str(e)
            logger.error(f"Metadata edit error: {e}")
        
        return result
    
    async def edit_batch(
        self,
        file_paths: List[Path],
        operations: List[MetadataOperation],
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> List[MetadataEditResult]:
        """
        Edit metadata of multiple files.
        
        Args:
            file_paths: List of file paths
            operations: Operations to apply to all files
            progress_callback: Progress callback
        
        Returns:
            List of MetadataEditResults
        """
        self._cancelled = False
        results = []
        snapshots = []
        total = len(file_paths)
        
        for i, file_path in enumerate(file_paths):
            if self._cancelled:
                break
            
            def file_progress(progress: float, message: str):
                overall = (i + progress) / total
                if progress_callback:
                    progress_callback(overall, message)
            
            result = await self.edit(file_path, operations, file_progress)
            results.append(result)
            
            if result.snapshot:
                snapshots.append(result.snapshot)
        
        # Add to undo stack
        if snapshots:
            self._add_to_undo_stack(snapshots)
        
        return results
    
    async def undo(
        self,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> bool:
        """
        Undo the last batch operation.
        
        Returns:
            True if undo was successful
        """
        if not self._undo_stack:
            return False
        
        snapshots = self._undo_stack.pop()
        redo_snapshots = []
        total = len(snapshots)
        
        for i, snapshot in enumerate(snapshots):
            if progress_callback:
                progress = (i + 1) / total
                progress_callback(progress, f"Undoing {snapshot.file_path.name}...")
            
            try:
                # Read current state for redo
                current = await self._read_metadata(snapshot.file_path)
                redo_snapshot = MetadataSnapshot(
                    file_path=snapshot.file_path,
                    original_metadata=current,
                    modified_metadata=snapshot.original_metadata,
                )
                redo_snapshots.append(redo_snapshot)
                
                # Restore original metadata
                await self._write_metadata(
                    snapshot.file_path,
                    snapshot.original_metadata
                )
            except Exception as e:
                logger.error(f"Undo error for {snapshot.file_path}: {e}")
        
        # Add to redo stack
        if redo_snapshots:
            self._redo_stack.append(redo_snapshots)
        
        return True
    
    async def redo(
        self,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> bool:
        """
        Redo the last undone operation.
        
        Returns:
            True if redo was successful
        """
        if not self._redo_stack:
            return False
        
        snapshots = self._redo_stack.pop()
        undo_snapshots = []
        total = len(snapshots)
        
        for i, snapshot in enumerate(snapshots):
            if progress_callback:
                progress = (i + 1) / total
                progress_callback(progress, f"Redoing {snapshot.file_path.name}...")
            
            try:
                # Read current state for undo
                current = await self._read_metadata(snapshot.file_path)
                undo_snapshot = MetadataSnapshot(
                    file_path=snapshot.file_path,
                    original_metadata=current,
                    modified_metadata=snapshot.modified_metadata,
                )
                undo_snapshots.append(undo_snapshot)
                
                # Apply modified metadata
                await self._write_metadata(
                    snapshot.file_path,
                    snapshot.modified_metadata
                )
            except Exception as e:
                logger.error(f"Redo error for {snapshot.file_path}: {e}")
        
        # Add to undo stack
        if undo_snapshots:
            self._undo_stack.append(undo_snapshots)
        
        return True
    
    def can_undo(self) -> bool:
        """Check if undo is available."""
        return bool(self._undo_stack)
    
    def can_redo(self) -> bool:
        """Check if redo is available."""
        return bool(self._redo_stack)
    
    def clear_history(self) -> None:
        """Clear undo/redo history."""
        self._undo_stack.clear()
        self._redo_stack.clear()
    
    def _add_to_undo_stack(self, snapshots: List[MetadataSnapshot]) -> None:
        """Add snapshots to undo stack."""
        self._undo_stack.append(snapshots)
        self._redo_stack.clear()  # Clear redo on new operation
        
        # Limit history size
        while len(self._undo_stack) > self.max_undo_history:
            self._undo_stack.pop(0)
    
    def _apply_operation(
        self,
        metadata: Dict[str, Any],
        operation: MetadataOperation,
    ) -> Dict[str, Any]:
        """Apply a single operation to metadata."""
        field_name = operation.get_field_name()
        current_value = metadata.get(field_name, "")
        
        if operation.operation == OperationType.SET:
            metadata[field_name] = operation.value
        
        elif operation.operation == OperationType.APPEND:
            if current_value:
                metadata[field_name] = f"{current_value}{operation.value}"
            else:
                metadata[field_name] = operation.value
        
        elif operation.operation == OperationType.PREPEND:
            if current_value:
                metadata[field_name] = f"{operation.value}{current_value}"
            else:
                metadata[field_name] = operation.value
        
        elif operation.operation == OperationType.REPLACE:
            if current_value and operation.find:
                metadata[field_name] = str(current_value).replace(
                    operation.find, operation.replace_with
                )
        
        elif operation.operation == OperationType.CLEAR:
            metadata[field_name] = ""
        
        elif operation.operation == OperationType.COPY:
            if operation.source_field:
                source_name = (
                    operation.source_field.value
                    if isinstance(operation.source_field, MetadataField)
                    else operation.source_field
                )
                metadata[field_name] = metadata.get(source_name, "")
        
        elif operation.operation == OperationType.FORMAT:
            # Apply format pattern with placeholders
            metadata[field_name] = self._apply_format(
                operation.format_pattern, metadata
            )
        
        return metadata
    
    def _apply_format(self, pattern: str, metadata: Dict[str, Any]) -> str:
        """Apply a format pattern with metadata placeholders."""
        result = pattern
        for key, value in metadata.items():
            placeholder = f"{{{key}}}"
            if placeholder in result:
                result = result.replace(placeholder, str(value or ""))
        return result
    
    async def _read_metadata(self, file_path: Path) -> Dict[str, Any]:
        """Read metadata from an audio file."""
        try:
            from mutagen import File as MutagenFile
        except ImportError:
            raise RuntimeError("mutagen is required for metadata editing")
        
        def read():
            audio = MutagenFile(str(file_path), easy=True)
            if audio is None:
                return {}
            
            metadata = {}
            for key in audio.keys():
                value = audio.get(key)
                if isinstance(value, list):
                    metadata[key] = value[0] if value else ""
                else:
                    metadata[key] = value
            return metadata
        
        return await asyncio.to_thread(read)
    
    async def _write_metadata(self, file_path: Path, metadata: Dict[str, Any]) -> None:
        """Write metadata to an audio file."""
        try:
            from mutagen import File as MutagenFile
        except ImportError:
            raise RuntimeError("mutagen is required for metadata editing")
        
        def write():
            audio = MutagenFile(str(file_path), easy=True)
            if audio is None:
                raise ValueError(f"Cannot open file: {file_path}")
            
            for key, value in metadata.items():
                if value:
                    audio[key] = str(value)
                elif key in audio:
                    del audio[key]
            
            audio.save()
        
        await asyncio.to_thread(write)
