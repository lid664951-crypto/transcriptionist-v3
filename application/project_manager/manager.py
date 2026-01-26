"""
Project Manager

High-level project management service.
Inspired by Quod Libet's PlaylistLibrary pattern.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable, Set, Dict, Any

from ...domain.models.project import Project
from ...domain.models.audio_file import AudioFile
from .repository import ProjectRepository

logger = logging.getLogger(__name__)

# Type alias for event callbacks
ProjectCallback = Callable[[Project], None]
ProjectsCallback = Callable[[List[Project]], None]


class ProjectManager:
    """
    High-level project management service.
    
    Provides:
    - Project CRUD with validation
    - File-to-project associations
    - Event notifications for UI updates
    - Search and filtering
    """
    
    def __init__(self, projects_dir: Path, library=None):
        """
        Initialize the project manager.
        
        Args:
            projects_dir: Directory for storing project files
            library: Optional audio file library for file lookups
        """
        self.repository = ProjectRepository(projects_dir)
        self.library = library
        
        # Event callbacks
        self._on_created: List[ProjectCallback] = []
        self._on_updated: List[ProjectCallback] = []
        self._on_deleted: List[ProjectCallback] = []
        self._on_changed: List[ProjectsCallback] = []
    
    # Event subscription
    
    def on_created(self, callback: ProjectCallback) -> None:
        """Subscribe to project created events."""
        self._on_created.append(callback)
    
    def on_updated(self, callback: ProjectCallback) -> None:
        """Subscribe to project updated events."""
        self._on_updated.append(callback)
    
    def on_deleted(self, callback: ProjectCallback) -> None:
        """Subscribe to project deleted events."""
        self._on_deleted.append(callback)
    
    def on_changed(self, callback: ProjectsCallback) -> None:
        """Subscribe to any project change events."""
        self._on_changed.append(callback)
    
    def _emit_created(self, project: Project) -> None:
        """Emit project created event."""
        for callback in self._on_created:
            try:
                callback(project)
            except Exception as e:
                logger.error(f"Error in created callback: {e}")
        self._emit_changed([project])
    
    def _emit_updated(self, project: Project) -> None:
        """Emit project updated event."""
        for callback in self._on_updated:
            try:
                callback(project)
            except Exception as e:
                logger.error(f"Error in updated callback: {e}")
        self._emit_changed([project])
    
    def _emit_deleted(self, project: Project) -> None:
        """Emit project deleted event."""
        for callback in self._on_deleted:
            try:
                callback(project)
            except Exception as e:
                logger.error(f"Error in deleted callback: {e}")
        self._emit_changed([project])
    
    def _emit_changed(self, projects: List[Project]) -> None:
        """Emit projects changed event."""
        for callback in self._on_changed:
            try:
                callback(projects)
            except Exception as e:
                logger.error(f"Error in changed callback: {e}")
    
    # CRUD Operations
    
    def create_project(
        self,
        name: str,
        description: str = "",
        template_name: Optional[str] = None,
    ) -> Project:
        """
        Create a new project.
        
        Args:
            name: Project name
            description: Optional description
            template_name: Optional template to use
        
        Returns:
            Created project
        
        Raises:
            ValueError: If name is empty or already exists
        """
        # Validate name
        name = name.strip()
        if not name:
            raise ValueError("Project name cannot be empty")
        
        if self.repository.get_by_name(name):
            raise ValueError(f"Project '{name}' already exists")
        
        project = Project(
            name=name,
            description=description,
            template_name=template_name,
        )
        
        project = self.repository.create(project)
        self._emit_created(project)
        
        return project
    
    def create_from_files(
        self,
        name: str,
        file_ids: List[int],
        description: str = "",
    ) -> Project:
        """
        Create a project from a list of files.
        
        Args:
            name: Project name
            file_ids: List of audio file IDs
            description: Optional description
        
        Returns:
            Created project
        """
        project = self.create_project(name, description)
        project.file_ids = file_ids.copy()
        self.repository.update(project)
        
        return project
    
    def get_project(self, project_id: int) -> Optional[Project]:
        """Get a project by ID."""
        return self.repository.get(project_id)
    
    def get_project_by_name(self, name: str) -> Optional[Project]:
        """Get a project by name."""
        return self.repository.get_by_name(name)
    
    def get_all_projects(self) -> List[Project]:
        """Get all projects."""
        return self.repository.get_all()
    
    def update_project(
        self,
        project_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[Project]:
        """
        Update a project's metadata.
        
        Args:
            project_id: Project ID
            name: New name (optional)
            description: New description (optional)
        
        Returns:
            Updated project or None if not found
        """
        project = self.repository.get(project_id)
        if not project:
            return None
        
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("Project name cannot be empty")
            
            # Check for duplicate name
            existing = self.repository.get_by_name(name)
            if existing and existing.id != project_id:
                raise ValueError(f"Project '{name}' already exists")
            
            project.name = name
        
        if description is not None:
            project.description = description
        
        if self.repository.update(project):
            self._emit_updated(project)
            return project
        
        return None
    
    def delete_project(self, project_id: int) -> bool:
        """
        Delete a project.
        
        Args:
            project_id: Project ID
        
        Returns:
            True if deleted
        """
        project = self.repository.get(project_id)
        if not project:
            return False
        
        if self.repository.delete(project_id):
            self._emit_deleted(project)
            return True
        
        return False
    
    def rename_project(self, project_id: int, new_name: str) -> Optional[Project]:
        """
        Rename a project.
        
        Args:
            project_id: Project ID
            new_name: New name
        
        Returns:
            Updated project or None
        """
        return self.update_project(project_id, name=new_name)
    
    # File associations
    
    def add_files_to_project(
        self,
        project_id: int,
        file_ids: List[int],
    ) -> Optional[Project]:
        """
        Add files to a project.
        
        Args:
            project_id: Project ID
            file_ids: List of file IDs to add
        
        Returns:
            Updated project or None
        """
        project = self.repository.get(project_id)
        if not project:
            return None
        
        for file_id in file_ids:
            project.add_file(file_id)
        
        if self.repository.update(project):
            self._emit_updated(project)
            return project
        
        return None
    
    def remove_files_from_project(
        self,
        project_id: int,
        file_ids: List[int],
    ) -> Optional[Project]:
        """
        Remove files from a project.
        
        Args:
            project_id: Project ID
            file_ids: List of file IDs to remove
        
        Returns:
            Updated project or None
        """
        project = self.repository.get(project_id)
        if not project:
            return None
        
        for file_id in file_ids:
            project.remove_file(file_id)
        
        if self.repository.update(project):
            self._emit_updated(project)
            return project
        
        return None
    
    def get_projects_for_file(self, file_id: int) -> List[Project]:
        """
        Get all projects containing a file.
        
        Args:
            file_id: File ID
        
        Returns:
            List of projects containing the file
        """
        return [
            project for project in self.repository
            if project.has_file(file_id)
        ]
    
    def get_files_in_project(self, project_id: int) -> List[int]:
        """
        Get all file IDs in a project.
        
        Args:
            project_id: Project ID
        
        Returns:
            List of file IDs
        """
        project = self.repository.get(project_id)
        if not project:
            return []
        return project.file_ids.copy()
    
    # Search and filtering
    
    def search_projects(self, query: str) -> List[Project]:
        """
        Search projects by name or description.
        
        Args:
            query: Search query
        
        Returns:
            Matching projects
        """
        query = query.lower()
        results = []
        
        for project in self.repository:
            if (query in project.name.lower() or 
                query in project.description.lower()):
                results.append(project)
        
        return results
    
    def get_recent_projects(self, limit: int = 10) -> List[Project]:
        """
        Get recently modified projects.
        
        Args:
            limit: Maximum number of projects
        
        Returns:
            List of recent projects
        """
        projects = self.repository.get_all()
        projects.sort(
            key=lambda p: p.modified_at or datetime.min,
            reverse=True
        )
        return projects[:limit]
    
    def get_projects_by_template(self, template_name: str) -> List[Project]:
        """
        Get projects using a specific template.
        
        Args:
            template_name: Template name
        
        Returns:
            List of projects using the template
        """
        return [
            project for project in self.repository
            if project.template_name == template_name
        ]
    
    # Statistics
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get project statistics.
        
        Returns:
            Dictionary with statistics
        """
        projects = self.repository.get_all()
        
        total_files = sum(p.file_count for p in projects)
        templates_used = set(p.template_name for p in projects if p.template_name)
        
        return {
            'total_projects': len(projects),
            'total_files': total_files,
            'templates_used': len(templates_used),
            'avg_files_per_project': total_files / len(projects) if projects else 0,
        }
