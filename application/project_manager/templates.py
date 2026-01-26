"""
Project Templates

Provides template functionality for creating projects with predefined settings.
Inspired by Quod Libet's playlist library patterns.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...domain.models.project import Project

logger = logging.getLogger(__name__)


@dataclass
class ProjectTemplate:
    """
    Template for creating projects with predefined settings.
    
    Templates define default values and structure for new projects.
    """
    
    # Identity
    id: str = ""
    name: str = ""
    description: str = ""
    
    # Template settings
    is_builtin: bool = False
    icon_name: str = "folder-symbolic"
    
    # Default project settings
    default_description: str = ""
    default_tags: List[str] = field(default_factory=list)
    
    # Export settings
    export_format: str = "flat"  # flat, category, date
    naming_scheme: str = "original"  # original, ucs, sequential
    include_metadata: bool = True
    
    # Metadata
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'is_builtin': self.is_builtin,
            'icon_name': self.icon_name,
            'default_description': self.default_description,
            'default_tags': self.default_tags.copy(),
            'export_format': self.export_format,
            'naming_scheme': self.naming_scheme,
            'include_metadata': self.include_metadata,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'modified_at': self.modified_at.isoformat() if self.modified_at else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProjectTemplate':
        """Create template from dictionary."""
        created_at = None
        if data.get('created_at'):
            created_at = datetime.fromisoformat(data['created_at'])
        
        modified_at = None
        if data.get('modified_at'):
            modified_at = datetime.fromisoformat(data['modified_at'])
        
        return cls(
            id=data.get('id', ''),
            name=data.get('name', ''),
            description=data.get('description', ''),
            is_builtin=data.get('is_builtin', False),
            icon_name=data.get('icon_name', 'folder-symbolic'),
            default_description=data.get('default_description', ''),
            default_tags=data.get('default_tags', []).copy(),
            export_format=data.get('export_format', 'flat'),
            naming_scheme=data.get('naming_scheme', 'original'),
            include_metadata=data.get('include_metadata', True),
            created_at=created_at,
            modified_at=modified_at,
        )
    
    def create_project(self, name: str) -> Project:
        """Create a new project from this template."""
        return Project(
            name=name,
            description=self.default_description,
            template_name=self.name,
            created_at=datetime.now(),
            modified_at=datetime.now(),
        )


# Built-in templates
BUILTIN_TEMPLATES = [
    ProjectTemplate(
        id='sfx-project',
        name='SFX Project',
        description='Standard sound effects project with UCS naming',
        is_builtin=True,
        icon_name='audio-x-generic-symbolic',
        default_description='Sound effects collection',
        default_tags=['sfx', 'sound-effects'],
        export_format='category',
        naming_scheme='ucs',
        include_metadata=True,
    ),
    ProjectTemplate(
        id='music-project',
        name='Music Project',
        description='Music production project',
        is_builtin=True,
        icon_name='audio-x-generic-symbolic',
        default_description='Music project',
        default_tags=['music'],
        export_format='flat',
        naming_scheme='original',
        include_metadata=True,
    ),
    ProjectTemplate(
        id='foley-project',
        name='Foley Project',
        description='Foley recording session project',
        is_builtin=True,
        icon_name='microphone-sensitivity-high-symbolic',
        default_description='Foley recording session',
        default_tags=['foley', 'recording'],
        export_format='category',
        naming_scheme='ucs',
        include_metadata=True,
    ),
    ProjectTemplate(
        id='ambience-project',
        name='Ambience Project',
        description='Ambient sound collection',
        is_builtin=True,
        icon_name='weather-clear-symbolic',
        default_description='Ambient sounds collection',
        default_tags=['ambience', 'atmosphere'],
        export_format='category',
        naming_scheme='ucs',
        include_metadata=True,
    ),
    ProjectTemplate(
        id='delivery-project',
        name='Delivery Project',
        description='Project for client delivery with sequential naming',
        is_builtin=True,
        icon_name='mail-send-symbolic',
        default_description='Client delivery package',
        default_tags=['delivery'],
        export_format='flat',
        naming_scheme='sequential',
        include_metadata=True,
    ),
    ProjectTemplate(
        id='empty-project',
        name='Empty Project',
        description='Blank project with no preset settings',
        is_builtin=True,
        icon_name='folder-new-symbolic',
        default_description='',
        default_tags=[],
        export_format='flat',
        naming_scheme='original',
        include_metadata=False,
    ),
]



class ProjectTemplateManager:
    """
    Manages project templates including built-in and custom templates.
    
    Features:
    - Built-in templates for common use cases
    - Custom user templates
    - Template persistence
    - Template CRUD operations
    """
    
    def __init__(self, templates_dir: Optional[Path] = None):
        """
        Initialize the template manager.
        
        Args:
            templates_dir: Directory for storing custom templates
        """
        self.templates_dir = templates_dir
        self._templates: Dict[str, ProjectTemplate] = {}
        self._load_builtin_templates()
        
        if templates_dir:
            self._load_custom_templates()
    
    def _load_builtin_templates(self) -> None:
        """Load built-in templates."""
        for template in BUILTIN_TEMPLATES:
            self._templates[template.id] = template
        logger.debug(f"Loaded {len(BUILTIN_TEMPLATES)} built-in templates")
    
    def _load_custom_templates(self) -> None:
        """Load custom templates from disk."""
        if not self.templates_dir or not self.templates_dir.exists():
            return
        
        templates_file = self.templates_dir / 'custom_templates.json'
        if not templates_file.exists():
            return
        
        try:
            with open(templates_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for template_data in data.get('templates', []):
                template = ProjectTemplate.from_dict(template_data)
                template.is_builtin = False
                self._templates[template.id] = template
            
            logger.info(f"Loaded {len(data.get('templates', []))} custom templates")
        except Exception as e:
            logger.error(f"Failed to load custom templates: {e}")
    
    def _save_custom_templates(self) -> None:
        """Save custom templates to disk."""
        if not self.templates_dir:
            return
        
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        templates_file = self.templates_dir / 'custom_templates.json'
        
        custom_templates = [
            t.to_dict() for t in self._templates.values()
            if not t.is_builtin
        ]
        
        try:
            with open(templates_file, 'w', encoding='utf-8') as f:
                json.dump({'templates': custom_templates}, f, ensure_ascii=False, indent=2)
            logger.debug(f"Saved {len(custom_templates)} custom templates")
        except Exception as e:
            logger.error(f"Failed to save custom templates: {e}")
    
    # CRUD Operations
    
    def get_all(self) -> List[ProjectTemplate]:
        """Get all templates."""
        return list(self._templates.values())
    
    def get_builtin(self) -> List[ProjectTemplate]:
        """Get only built-in templates."""
        return [t for t in self._templates.values() if t.is_builtin]
    
    def get_custom(self) -> List[ProjectTemplate]:
        """Get only custom templates."""
        return [t for t in self._templates.values() if not t.is_builtin]
    
    def get(self, template_id: str) -> Optional[ProjectTemplate]:
        """Get a template by ID."""
        return self._templates.get(template_id)
    
    def get_by_name(self, name: str) -> Optional[ProjectTemplate]:
        """Get a template by name."""
        for template in self._templates.values():
            if template.name == name:
                return template
        return None
    
    def create(
        self,
        name: str,
        description: str = "",
        **kwargs,
    ) -> ProjectTemplate:
        """
        Create a new custom template.
        
        Args:
            name: Template name
            description: Template description
            **kwargs: Additional template settings
        
        Returns:
            Created template
        """
        # Generate unique ID
        template_id = self._generate_id(name)
        
        template = ProjectTemplate(
            id=template_id,
            name=name,
            description=description,
            is_builtin=False,
            icon_name=kwargs.get('icon_name', 'folder-symbolic'),
            default_description=kwargs.get('default_description', ''),
            default_tags=kwargs.get('default_tags', []),
            export_format=kwargs.get('export_format', 'flat'),
            naming_scheme=kwargs.get('naming_scheme', 'original'),
            include_metadata=kwargs.get('include_metadata', True),
            created_at=datetime.now(),
            modified_at=datetime.now(),
        )
        
        self._templates[template_id] = template
        self._save_custom_templates()
        
        logger.info(f"Created template: {name}")
        return template
    
    def create_from_project(
        self,
        project: Project,
        name: str,
        description: str = "",
    ) -> ProjectTemplate:
        """
        Create a template from an existing project.
        
        Args:
            project: Source project
            name: Template name
            description: Template description
        
        Returns:
            Created template
        """
        return self.create(
            name=name,
            description=description or f"Template based on {project.name}",
            default_description=project.description,
        )
    
    def update(
        self,
        template_id: str,
        **kwargs,
    ) -> Optional[ProjectTemplate]:
        """
        Update a custom template.
        
        Args:
            template_id: Template ID
            **kwargs: Fields to update
        
        Returns:
            Updated template or None if not found/builtin
        """
        template = self._templates.get(template_id)
        if not template or template.is_builtin:
            return None
        
        # Update fields
        for key, value in kwargs.items():
            if hasattr(template, key) and key not in ('id', 'is_builtin', 'created_at'):
                setattr(template, key, value)
        
        template.modified_at = datetime.now()
        self._save_custom_templates()
        
        logger.info(f"Updated template: {template.name}")
        return template
    
    def delete(self, template_id: str) -> bool:
        """
        Delete a custom template.
        
        Args:
            template_id: Template ID
        
        Returns:
            True if deleted, False if not found or builtin
        """
        template = self._templates.get(template_id)
        if not template or template.is_builtin:
            return False
        
        del self._templates[template_id]
        self._save_custom_templates()
        
        logger.info(f"Deleted template: {template.name}")
        return True
    
    def duplicate(
        self,
        template_id: str,
        new_name: Optional[str] = None,
    ) -> Optional[ProjectTemplate]:
        """
        Duplicate a template.
        
        Args:
            template_id: Source template ID
            new_name: Name for the new template
        
        Returns:
            New template or None if source not found
        """
        source = self._templates.get(template_id)
        if not source:
            return None
        
        name = new_name or f"{source.name} (Copy)"
        
        return self.create(
            name=name,
            description=source.description,
            icon_name=source.icon_name,
            default_description=source.default_description,
            default_tags=source.default_tags.copy(),
            export_format=source.export_format,
            naming_scheme=source.naming_scheme,
            include_metadata=source.include_metadata,
        )
    
    def _generate_id(self, name: str) -> str:
        """Generate a unique ID from a name."""
        # Convert to lowercase, replace spaces with dashes
        base_id = name.lower().replace(' ', '-')
        # Remove invalid characters
        base_id = ''.join(c for c in base_id if c.isalnum() or c == '-')
        
        # Ensure uniqueness
        if base_id not in self._templates:
            return base_id
        
        counter = 1
        while f"{base_id}-{counter}" in self._templates:
            counter += 1
        
        return f"{base_id}-{counter}"
    
    # Utility methods
    
    def get_default_template(self) -> ProjectTemplate:
        """Get the default template for new projects."""
        return self._templates.get('empty-project', BUILTIN_TEMPLATES[-1])
    
    def search(self, query: str) -> List[ProjectTemplate]:
        """Search templates by name or description."""
        query_lower = query.lower()
        return [
            t for t in self._templates.values()
            if query_lower in t.name.lower() or query_lower in t.description.lower()
        ]
