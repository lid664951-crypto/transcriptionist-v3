"""
Notification helper for consistent InfoBar usage across the application.
Simplifies InfoBar calls and ensures consistent styling.
"""

from typing import Optional

from PySide6.QtWidgets import QWidget
from qfluentwidgets import InfoBar, InfoBarPosition


class NotificationHelper:
    """
    Helper class for showing notifications using InfoBar.
    Provides a simplified interface with consistent styling.
    """
    
    @staticmethod
    def success(
        parent: QWidget,
        title: str,
        content: str,
        duration: int = 2000,
        position: InfoBarPosition = InfoBarPosition.TOP
    ) -> None:
        """
        Show a success notification.
        
        Args:
            parent: Parent widget
            title: Notification title
            content: Notification content
            duration: Duration in milliseconds (default 2000)
            position: Position of the notification
        """
        InfoBar.success(
            title=title,
            content=content,
            parent=parent,
            position=position,
            duration=duration
        )
    
    @staticmethod
    def warning(
        parent: QWidget,
        title: str,
        content: str,
        duration: int = 2000,
        position: InfoBarPosition = InfoBarPosition.TOP
    ) -> None:
        """
        Show a warning notification.
        
        Args:
            parent: Parent widget
            title: Notification title
            content: Notification content
            duration: Duration in milliseconds (default 2000)
            position: Position of the notification
        """
        InfoBar.warning(
            title=title,
            content=content,
            parent=parent,
            position=position,
            duration=duration
        )
    
    @staticmethod
    def error(
        parent: QWidget,
        title: str,
        content: str,
        duration: int = 3000,
        position: InfoBarPosition = InfoBarPosition.TOP
    ) -> None:
        """
        Show an error notification.
        
        Args:
            parent: Parent widget
            title: Notification title
            content: Notification content
            duration: Duration in milliseconds (default 3000)
            position: Position of the notification
        """
        InfoBar.error(
            title=title,
            content=content,
            parent=parent,
            position=position,
            duration=duration
        )
    
    @staticmethod
    def info(
        parent: QWidget,
        title: str,
        content: str,
        duration: int = 2000,
        position: InfoBarPosition = InfoBarPosition.TOP
    ) -> None:
        """
        Show an info notification.
        
        Args:
            parent: Parent widget
            title: Notification title
            content: Notification content
            duration: Duration in milliseconds (default 2000)
            position: Position of the notification
        """
        InfoBar.info(
            title=title,
            content=content,
            parent=parent,
            position=position,
            duration=duration
        )
