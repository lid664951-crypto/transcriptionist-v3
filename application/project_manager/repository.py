"""
Project Repository

Handles persistence of projects using JSON files.
Inspired by Quod Libet's XSPFBackedPlaylist approach.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Iterator
from xml.etree import ElementTree as ET

from ...domain.models.project import Project

logger = logging.getLogger(__name__)

# Project file extension
PROJECT_EXT = ".tproj"  # Transcriptionist Project


class ProjectRepository:
    """
    Repository for persisting and loading projects.
    
    Projects are stored as JSON files in a dedicated directory.
    Each project file contains:
    - Project metadata (name, description, etc.)
    - List of file paths (relative or absolute)
    - Template information
    - Timestamps
    """
    
    def __init__(self, projects_dir: Path):
        """
        Initialize the repository.
        
        Args:
            projects_dir: Directory to store project files
        """
        self.projects_dir = Path(projects_dir)
        self._ensure_directory()
        self._projects: Dict[int, Project] = {}
        self._next_id = 1
        self._load_all()
    
    def _ensure_directory(self) -> None:
        """Ensure the projects directory exists."""
        self.projects_dir.mkdir(parents=True, exist_ok=True)
    
    def _load_all(self) -> None:
        """Load all projects from disk."""
        logger.info(f"Loading projects from {self.projects_dir}")
        
        for file_path in self.projects_dir.glob(f"*{PROJECT_EXT}"):
            try:
                project = self._load_project_file(file_path)
                if project:
                    self._projects[project.id] = project
                    if project.id >= self._next_id:
                        self._next_id = project.id + 1
            except Exception as e:
                logger.error(f"Failed to load project {file_path}: {e}")
        
        logger.info(f"Loaded {len(self._projects)} projects")
    
    def _load_project_file(self, file_path: Path) -> Optional[Project]:
        """Load a single project from file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            project = Project.from_dict(data)
            project._file_path = str(file_path)  # Store file path for updates
            return project
        
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {file_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            return None
    
    def _save_project_file(self, project: Project) -> bool:
        """Save a project to file."""
        try:
            file_path = self._get_project_path(project)
            
            data = project.to_dict()
            data['_version'] = 1  # File format version
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            project._file_path = str(file_path)
            logger.debug(f"Saved project {project.name} to {file_path}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to save project {project.name}: {e}")
            return False
    
    def _get_project_path(self, project: Project) -> Path:
        """Get the file path for a project."""
        # Sanitize name for filename
        safe_name = self._sanitize_filename(project.name)
        return self.projects_dir / f"{safe_name}_{project.id}{PROJECT_EXT}"
    
    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string for use as a filename."""
        # Remove or replace invalid characters
        invalid_chars = '<>:"/\\|?*'
        result = name
        for char in invalid_chars:
            result = result.replace(char, '_')
        
        # Limit length
        if len(result) > 50:
            result = result[:50]
        
        return result.strip() or 'untitled'
    
    # CRUD Operations
    
    def create(self, project: Project) -> Project:
        """
        Create a new project.
        
        Args:
            project: Project to create (id will be assigned)
        
        Returns:
            Created project with assigned id
        """
        project.id = self._next_id
        self._next_id += 1
        
        project.created_at = datetime.now()
        project.modified_at = project.created_at
        
        if self._save_project_file(project):
            self._projects[project.id] = project
            logger.info(f"Created project: {project.name} (id={project.id})")
        
        return project
    
    def get(self, project_id: int) -> Optional[Project]:
        """
        Get a project by ID.
        
        Args:
            project_id: Project ID
        
        Returns:
            Project if found, None otherwise
        """
        return self._projects.get(project_id)
    
    def get_by_name(self, name: str) -> Optional[Project]:
        """
        Get a project by name.
        
        Args:
            name: Project name
        
        Returns:
            Project if found, None otherwise
        """
        for project in self._projects.values():
            if project.name == name:
                return project
        return None
    
    def get_all(self) -> List[Project]:
        """
        Get all projects.
        
        Returns:
            List of all projects
        """
        return list(self._projects.values())
    
    def update(self, project: Project) -> bool:
        """
        Update an existing project.
        
        Args:
            project: Project to update
        
        Returns:
            True if successful
        """
        if project.id not in self._projects:
            logger.warning(f"Project {project.id} not found for update")
            return False
        
        project.modified_at = datetime.now()
        
        # Handle rename (file path changes)
        old_project = self._projects[project.id]
        old_path = getattr(old_project, '_file_path', None)
        
        if self._save_project_file(project):
            # Delete old file if name changed
            if old_path and old_path != project._file_path:
                try:
                    os.unlink(old_path)
                except OSError:
                    pass
            
            self._projects[project.id] = project
            logger.info(f"Updated project: {project.name}")
            return True
        
        return False
    
    def delete(self, project_id: int) -> bool:
        """
        Delete a project.
        
        Args:
            project_id: ID of project to delete
        
        Returns:
            True if successful
        """
        project = self._projects.get(project_id)
        if not project:
            return False
        
        # Delete file
        file_path = getattr(project, '_file_path', None)
        if file_path:
            try:
                os.unlink(file_path)
            except OSError as e:
                logger.warning(f"Failed to delete project file: {e}")
        
        del self._projects[project_id]
        logger.info(f"Deleted project: {project.name}")
        return True
    
    def __iter__(self) -> Iterator[Project]:
        """Iterate over all projects."""
        return iter(self._projects.values())
    
    def __len__(self) -> int:
        """Get number of projects."""
        return len(self._projects)
    
    def __contains__(self, project_id: int) -> bool:
        """Check if project exists."""
        return project_id in self._projects
