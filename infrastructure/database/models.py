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
    
    # Indexes
    __table_args__ = (
        Index('idx_audio_files_filename', 'filename'),
        Index('idx_audio_files_hash', 'content_hash'),
        Index('idx_audio_files_duration', 'duration'),
        Index('idx_audio_files_sample_rate', 'sample_rate'),
        Index('idx_audio_files_format', 'format'),
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
    )
    
    def __repr__(self) -> str:
        return f"<AudioFileTag(id={self.id}, tag='{self.tag}')>"


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
