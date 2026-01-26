"""
UI Module

基于 PyQt6 + Fluent Widgets 的现代化用户界面。
采用 Fluent Design 设计风格。

模块结构：
- main_window.py: 主窗口类 (TranscriptionistWindow)
- pages/: 页面模块 (音效库、AI翻译、命名规则等)
"""


def run():
    """运行应用程序"""
    from .main_window import run_app
    return run_app()


__all__ = [
    'run',
]
