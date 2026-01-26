"""
页面模块 - PySide6 + Fluent Widgets 版本
"""

__all__ = [
    'LibraryPage',
    'AITranslatePage', 
    'NamingRulesPage',
    'OnlineResourcesPage',
    'ProjectsPage',
    'ToolboxPage',
    'SettingsPage',
]

def __getattr__(name):
    """延迟导入"""
    if name == 'LibraryPage':
        from .library_page_qt import LibraryPage
        return LibraryPage
    elif name == 'AITranslatePage':
        from .ai_translate_page_qt import AITranslatePage
        return AITranslatePage
    elif name == 'NamingRulesPage':
        from .naming_rules_page_qt import NamingRulesPage
        return NamingRulesPage
    elif name == 'OnlineResourcesPage':
        from .online_resources_page_qt import OnlineResourcesPage
        return OnlineResourcesPage
    elif name == 'ProjectsPage':
        from .projects_page_qt import ProjectsPage
        return ProjectsPage
    elif name == 'ToolboxPage':
        from .toolbox_page_qt import ToolboxPage
        return ToolboxPage
    elif name == 'SettingsPage':
        from .settings_page_qt import SettingsPage
        return SettingsPage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
