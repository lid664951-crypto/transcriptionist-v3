"""
SQLAlchemy Database Models

Defines the database models for AudioFile, Project, SavedSearch and related entities.

Validates: Requirements 1.1, 1.2, 7.1, 7.2, 10.1
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, Boolean,
    ForeignKey, Table, Index, JSON, LargeBinary
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


# Association table for many-to-many relationship between projects and audio files
project_files = Table(
    'project_files',
    Base.metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('project_id', Integer, ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
    Column('audio_file_id', Integer, ForeignKey('audio_files.id', ondelete='CASCADE'), nullable=False),
    Column('added_at', DateTime, default=datetime.utcnow),
    Index('idx_project_files_project', 'project_id'),
    Index('idx_project_files_audio', 'audio_file_id'),
)


class AudioFile(Base):
    """
    Represents an audio file in the library.
    
    Stores file metadata, audio properties, and relationships to projects and tags.
    """
    __tablename__ = 'audio_files'
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # File information
    file_path: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False, index=True, default="")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    
    # Audio properties
    duration: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    bit_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    channels: Mapped[int] = mapped_column(Integer, nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    
    # Metadata
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    translated_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # AI processing status (0: pending, 1: done, 2: failed)
    index_status: Mapped[int] = mapped_column(Integer, default=0, index=True)
    index_version: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    tag_status: Mapped[int] = mapped_column(Integer, default=0, index=True)
    tag_version: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    translation_status: Mapped[int] = mapped_column(Integer, default=0, index=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    modified_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_played_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    tags: Mapped[List["AudioFileTag"]] = relationship(
        "AudioFileTag", back_populates="audio_file", cascade="all, delete-orphan"
    )
    custom_fields: Mapped[List["AudioFileCustomField"]] = relationship(
        "AudioFileCustomField", back_populates="audio_file", cascade="all, delete-orphan"
    )
    projects: Mapped[List["Project"]] = relationship(
        "Project", secondary=project_files, back_populates="files"
    )
    
    # Indexes（含复合索引以优化百万级查询：格式+时长、采样率+位深、常见搜索组合）
    __table_args__ = (
        Index('idx_audio_files_filename', 'filename'),
        Index('idx_audio_files_hash', 'content_hash'),
        Index('idx_audio_files_duration', 'duration'),
        Index('idx_audio_files_sample_rate', 'sample_rate'),
        Index('idx_audio_files_format', 'format'),
        Index('idx_audio_files_format_duration', 'format', 'duration'),
        Index('idx_audio_files_sample_bit_depth', 'sample_rate', 'bit_depth'),
        Index('idx_audio_files_search', 'filename', 'duration', 'format'),
    )
    
    def __repr__(self) -> str:
        return f"<AudioFile(id={self.id}, filename='{self.filename}')>"


class AudioFileTag(Base):
    """Tags associated with audio files."""
    __tablename__ = 'audio_file_tags'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audio_file_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('audio_files.id', ondelete='CASCADE'), nullable=False
    )
    tag: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    
    # Relationship
    audio_file: Mapped["AudioFile"] = relationship("AudioFile", back_populates="tags")
    
    __table_args__ = (
        Index('idx_audio_file_tags_tag', 'tag'),
        Index('idx_audio_file_tags_audio_file_id', 'audio_file_id'),
    )
    
    def __repr__(self) -> str:
        return f"<AudioFileTag(id={self.id}, tag='{self.tag}')>"


class ImportQueue(Base):
    """导入队列表：记录待入库的音频文件路径。"""
    __tablename__ = "import_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False, index=True)
    root_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True, index=True)
    status: Mapped[int] = mapped_column(Integer, default=0, index=True)  # 0: pending, 1: processing, 2: done, 3: skipped, 4: failed
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<ImportQueue(id={self.id}, status={self.status}, path='{self.file_path}')>"


class AudioFileCustomField(Base):
    """Custom metadata fields for audio files."""
    __tablename__ = 'audio_file_custom_fields'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audio_file_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('audio_files.id', ondelete='CASCADE'), nullable=False
    )
    field_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    field_value: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Relationship
    audio_file: Mapped["AudioFile"] = relationship("AudioFile", back_populates="custom_fields")
    
    __table_args__ = (
        Index('idx_custom_fields_name', 'field_name'),
    )
    
    def __repr__(self) -> str:
        return f"<AudioFileCustomField(id={self.id}, name='{self.field_name}')>"


class Project(Base):
    """
    Represents a project for organizing audio files.
    
    Projects can contain multiple audio files and support templates.
    """
    __tablename__ = 'projects'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    template_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    modified_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    files: Mapped[List["AudioFile"]] = relationship(
        "AudioFile", secondary=project_files, back_populates="projects"
    )
    
    @property
    def file_count(self) -> int:
        """Get the number of files in this project."""
        return len(self.files)
    
    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name='{self.name}')>"


class SavedSearch(Base):
    """
    Represents a saved search query.
    
    Allows users to save and recall frequently used search queries.
    """
    __tablename__ = 'saved_searches'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    query_string: Mapped[str] = mapped_column(Text, nullable=False)
    filters: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)  # JSON encoded filters
    
    # Usage tracking
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    def __repr__(self) -> str:
        return f"<SavedSearch(id={self.id}, name='{self.name}')>"


class LibraryPath(Base):
    """
    Represents a library path that is scanned for audio files.
    """
    __tablename__ = 'library_paths'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    recursive: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Scan status
    last_scan_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    def __repr__(self) -> str:
        return f"<LibraryPath(id={self.id}, path='{self.path}')>"


class WaveformCache(Base):
    """
    Cached waveform data for audio files.
    """
    __tablename__ = 'waveform_cache'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audio_file_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('audio_files.id', ondelete='CASCADE'), unique=True, nullable=False
    )
    waveform_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    def __repr__(self) -> str:
        return f"<WaveformCache(id={self.id}, audio_file_id={self.audio_file_id})>"


class RenameHistory(Base):
    """
    History of file rename operations for undo support.
    """
    __tablename__ = 'rename_history'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audio_file_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('audio_files.id', ondelete='CASCADE'), nullable=False
    )
    old_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    new_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    old_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    new_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    
    # Timestamps
    renamed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    def __repr__(self) -> str:
        return f"<RenameHistory(id={self.id}, old='{self.old_filename}', new='{self.new_filename}')>"


class Job(Base):
    """
    Background job for long-running tasks (indexing/tagging/translation).
    """
    __tablename__ = 'jobs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # pending/running/paused/failed/done
    selection: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    checkpoint: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items: Mapped[List["JobItem"]] = relationship(
        "JobItem", back_populates="job", cascade="all, delete-orphan"
    )
    index_shards: Mapped[List["IndexShard"]] = relationship(
        "IndexShard", back_populates="job", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Job(id={self.id}, type='{self.job_type}', status='{self.status}')>"


class JobItem(Base):
    """Items bound to a job (used for explicit file list selection)."""
    __tablename__ = 'job_items'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False, index=True
    )
    audio_file_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey('audio_files.id', ondelete='CASCADE'), nullable=True, index=True
    )
    file_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True, index=True)
    status: Mapped[int] = mapped_column(Integer, default=0, index=True)  # 0 pending, 1 done, 2 failed
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    job: Mapped["Job"] = relationship("Job", back_populates="items")

    def __repr__(self) -> str:
        return f"<JobItem(id={self.id}, job_id={self.job_id}, status={self.status})>"


class IndexShard(Base):
    """Chunked index shard metadata."""
    __tablename__ = 'index_shards'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey('jobs.id', ondelete='SET NULL'), nullable=True, index=True
    )
    shard_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0)
    start_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job: Mapped[Optional["Job"]] = relationship("Job", back_populates="index_shards")

    def __repr__(self) -> str:
        return f"<IndexShard(id={self.id}, shard='{self.shard_path}')>"
