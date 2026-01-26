"""
Dialogs Module - Common dialog windows

Contains rename dialog, batch rename interface, template editor,
conflict resolution dialog, project dialogs, and other common dialogs.
"""

from .rename_dialog import RenameDialog, show_rename_dialog
from .batch_rename_dialog import BatchRenameDialog, show_batch_rename_dialog
from .template_editor_dialog import (
    TemplateEditorDialog,
    TemplateListDialog,
    show_template_editor,
    show_template_list,
)
from .conflict_resolution_dialog import (
    ConflictAction,
    ConflictResolutionDialog,
    BatchConflictResolutionDialog,
    show_conflict_dialog,
    show_batch_conflict_dialog,
)
from .project_creation_dialog import ProjectCreationDialog
from .export_wizard_dialog import ExportWizardDialog
from .batch_wizard_dialog import BatchWizardDialog

__all__ = [
    # Rename dialogs
    "RenameDialog",
    "show_rename_dialog",
    "BatchRenameDialog",
    "show_batch_rename_dialog",
    # Template dialogs
    "TemplateEditorDialog",
    "TemplateListDialog",
    "show_template_editor",
    "show_template_list",
    # Conflict resolution dialogs
    "ConflictAction",
    "ConflictResolutionDialog",
    "BatchConflictResolutionDialog",
    "show_conflict_dialog",
    "show_batch_conflict_dialog",
    # Project dialogs
    "ProjectCreationDialog",
    "ExportWizardDialog",
    # Batch processing dialogs
    "BatchWizardDialog",
]
