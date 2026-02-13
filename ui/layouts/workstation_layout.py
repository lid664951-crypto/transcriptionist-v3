"""
Workstation Layout - 为音效工作站设计的停靠式三栏布局
"""

from enum import Enum

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)
from qfluentwidgets import CaptionLabel, TransparentPushButton


class LayoutMode(str, Enum):
    SPLIT = "split"
    LIBRARY_FOCUS = "library_focus"
    WORKBENCH_FOCUS = "workbench_focus"


class CollapsiblePanel(QFrame):
    """可折叠的侧边面板"""

    collapsed_changed = Signal(bool)

    def __init__(self, title: str, collapse_direction: str = "left", parent=None):
        super().__init__(parent)
        self.setObjectName("collapsiblePanel")
        self._collapsed = False
        self._collapse_direction = collapse_direction
        self._expanded_width = 300
        self._title = title
        self._init_ui()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.header = QFrame()
        self.header.setFixedHeight(32)
        self.header.setObjectName("workstationPanelHeader")

        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(8, 0, 4, 0)
        header_layout.setSpacing(4)

        self.focus_library_btn = TransparentPushButton("‹")
        self.focus_library_btn.setObjectName("workstationFocusLibraryBtn")
        self.focus_library_btn.setFixedSize(24, 24)
        self.focus_library_btn.setToolTip("音效库全屏")
        self.focus_library_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.focus_workbench_btn = TransparentPushButton("›")
        self.focus_workbench_btn.setObjectName("workstationFocusWorkbenchBtn")
        self.focus_workbench_btn.setFixedSize(24, 24)
        self.focus_workbench_btn.setToolTip("工作台全屏")
        self.focus_workbench_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        chevron_font = QFont()
        chevron_font.setPointSize(14)
        chevron_font.setWeight(QFont.Weight.Light)
        self.focus_library_btn.setFont(chevron_font)
        self.focus_workbench_btn.setFont(chevron_font)

        self._update_collapse_icon()

        # 向后兼容：保留 collapse_btn 引用，避免外部调用崩溃
        self.collapse_btn = self.focus_library_btn

        self.title_label = CaptionLabel(self._title.upper())
        self.title_label.setObjectName("workstationPanelTitle")

        if self._collapse_direction == "left":
            header_layout.addWidget(self.title_label)
            header_layout.addStretch()
            header_layout.addWidget(self.focus_library_btn)
            header_layout.addWidget(self.focus_workbench_btn)
        else:
            header_layout.addWidget(self.focus_library_btn)
            header_layout.addWidget(self.focus_workbench_btn)
            header_layout.addWidget(self.title_label)
            header_layout.addStretch()

        self.main_layout.addWidget(self.header)

        self.content = QStackedWidget()
        self.content.setObjectName("workstationPanelContent")
        self.content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.main_layout.addWidget(self.content, 1)

    def _update_collapse_icon(self):
        self.focus_library_btn.setText("‹")
        self.focus_workbench_btn.setText("›")

    def toggle_collapsed(self):
        if self._collapsed:
            self.expand()
        else:
            self.collapse()

    def collapse(self):
        if self._collapsed:
            return
        self._expanded_width = max(self.width(), 200)
        self._collapsed = True
        self.content.hide()
        self.title_label.hide()
        self.setFixedWidth(32)
        self._update_collapse_icon()
        self.collapsed_changed.emit(True)

    def expand(self):
        if not self._collapsed:
            return
        self._collapsed = False
        self.setMinimumWidth(200)
        self.setMaximumWidth(16777215)
        self.content.show()
        self.title_label.show()
        self._update_collapse_icon()
        self.collapsed_changed.emit(False)

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed


class WorkstationLayout(QWidget):
    """核心布局组件，支持三态布局切换"""

    layout_mode_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout_mode = LayoutMode.SPLIT
        self._last_split_sizes = [280, 1000]
        self._setup_ui()
        self._apply_layout_mode(LayoutMode.SPLIT, emit_signal=False)

    def _setup_ui(self):
        self.setObjectName("workstationLayout")
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("workstationMainSplitter")
        self.main_splitter.setHandleWidth(1)

        self.left_panel = CollapsiblePanel("音效库", collapse_direction="left")
        self.left_panel.setObjectName("workstationLeftPanel")
        self.left_panel.setMinimumWidth(250)

        self.left_panel.focus_library_btn.clicked.connect(self._on_focus_library_clicked)
        self.left_panel.focus_workbench_btn.clicked.connect(self._on_focus_workbench_clicked)

        self.center_widget = QWidget()
        self.center_widget.setObjectName("workstationCenterWidget")
        self.center_widget.setMinimumWidth(0)
        center_layout = QVBoxLayout(self.center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        center_header = QFrame()
        center_header.setFixedHeight(32)
        center_header.setObjectName("workstationCenterHeader")
        center_header_layout = QHBoxLayout(center_header)
        center_header_layout.setContentsMargins(12, 0, 12, 0)

        center_title = CaptionLabel("工作台")
        center_title.setObjectName("workstationCenterTitle")
        center_header_layout.addWidget(center_title)

        self.center_focus_library_btn = TransparentPushButton("‹")
        self.center_focus_library_btn.setObjectName("workstationFocusLibraryBtn")
        self.center_focus_library_btn.setFixedSize(24, 24)
        self.center_focus_library_btn.setToolTip("音效库全屏")
        self.center_focus_library_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.center_focus_workbench_btn = TransparentPushButton("›")
        self.center_focus_workbench_btn.setObjectName("workstationFocusWorkbenchBtn")
        self.center_focus_workbench_btn.setFixedSize(24, 24)
        self.center_focus_workbench_btn.setToolTip("工作台全屏")
        self.center_focus_workbench_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        chevron_font = QFont()
        chevron_font.setPointSize(14)
        chevron_font.setWeight(QFont.Weight.Light)
        self.center_focus_library_btn.setFont(chevron_font)
        self.center_focus_workbench_btn.setFont(chevron_font)

        self.center_focus_library_btn.clicked.connect(self._on_focus_library_clicked)
        self.center_focus_workbench_btn.clicked.connect(self._on_focus_workbench_clicked)

        center_header_layout.addStretch()
        center_header_layout.addWidget(self.center_focus_library_btn)
        center_header_layout.addWidget(self.center_focus_workbench_btn)
        center_layout.addWidget(center_header)

        self.center_tabs = QTabWidget()
        self.center_tabs.setObjectName("workstationCenterTabs")
        self.center_tabs.setDocumentMode(True)
        self.center_tabs.tabBar().hide()
        center_layout.addWidget(self.center_tabs)

        self.main_splitter.addWidget(self.left_panel)
        self.main_splitter.addWidget(self.center_widget)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 4)
        self.main_splitter.setSizes(self._last_split_sizes)

        main_layout.addWidget(self.main_splitter)

    def _get_next_mode(self) -> LayoutMode:
        if self._layout_mode == LayoutMode.SPLIT:
            return LayoutMode.LIBRARY_FOCUS
        if self._layout_mode == LayoutMode.LIBRARY_FOCUS:
            return LayoutMode.WORKBENCH_FOCUS
        return LayoutMode.SPLIT

    def _capture_split_sizes(self):
        sizes = self.main_splitter.sizes()
        if len(sizes) == 2 and sizes[0] > 80 and sizes[1] > 80:
            self._last_split_sizes = sizes

    def _update_mode_button(self):
        button_pairs = [
            (self.left_panel.focus_library_btn, self.left_panel.focus_workbench_btn),
            (self.center_focus_library_btn, self.center_focus_workbench_btn),
        ]

        for left_btn, right_btn in button_pairs:
            if self._layout_mode == LayoutMode.SPLIT:
                left_btn.setToolTip("音效库全屏")
                right_btn.setToolTip("工作台全屏")
                left_btn.setProperty("active", False)
                right_btn.setProperty("active", False)
            elif self._layout_mode == LayoutMode.LIBRARY_FOCUS:
                left_btn.setToolTip("恢复分栏")
                right_btn.setToolTip("切换到工作台全屏")
                left_btn.setProperty("active", True)
                right_btn.setProperty("active", False)
            else:
                left_btn.setToolTip("切换到音效库全屏")
                right_btn.setToolTip("恢复分栏")
                left_btn.setProperty("active", False)
                right_btn.setProperty("active", True)

            left_btn.style().unpolish(left_btn)
            left_btn.style().polish(left_btn)
            right_btn.style().unpolish(right_btn)
            right_btn.style().polish(right_btn)

    def _on_focus_library_clicked(self):
        if self._layout_mode == LayoutMode.LIBRARY_FOCUS:
            self.restore_split()
            return
        self.focus_library()

    def _on_focus_workbench_clicked(self):
        if self._layout_mode == LayoutMode.WORKBENCH_FOCUS:
            self.restore_split()
            return
        self.focus_workbench()

    def _set_center_visible(self, visible: bool):
        if visible:
            self.center_widget.setVisible(True)
            self.center_widget.setMinimumWidth(0)
            self.center_widget.setMaximumWidth(16777215)
            return
        self.center_widget.setMinimumWidth(0)
        self.center_widget.setMaximumWidth(0)
        self.center_widget.setVisible(False)

    def _set_left_panel_visible(self, visible: bool):
        if visible:
            self.left_panel.setVisible(True)
            self.left_panel.setMinimumWidth(250)
            self.left_panel.setMaximumWidth(16777215)
            return
        self.left_panel.setMinimumWidth(0)
        self.left_panel.setMaximumWidth(0)
        self.left_panel.setVisible(False)

    def _apply_layout_mode(self, mode: LayoutMode, emit_signal: bool = True):
        if mode == self._layout_mode:
            self._update_mode_button()
            return

        if self._layout_mode == LayoutMode.SPLIT:
            self._capture_split_sizes()

        if mode == LayoutMode.SPLIT:
            self.main_splitter.setHandleWidth(1)
            self._set_left_panel_visible(True)
            self._set_center_visible(True)
            self.left_panel.expand()
            self.main_splitter.setSizes(self._last_split_sizes)
        elif mode == LayoutMode.LIBRARY_FOCUS:
            self.main_splitter.setHandleWidth(0)
            self._set_left_panel_visible(True)
            self.left_panel.expand()
            self._set_center_visible(False)
            self.main_splitter.setSizes([10000, 0])
        else:
            self.main_splitter.setHandleWidth(0)
            self._set_center_visible(True)
            # 工作台全屏：左侧彻底隐藏，避免残留侧边条影响视觉
            self._set_left_panel_visible(False)
            self.main_splitter.setSizes([0, 10000])

        self._layout_mode = mode
        self._update_mode_button()
        if emit_signal:
            self.layout_mode_changed.emit(mode.value)

    def set_layout_mode(self, mode: LayoutMode | str):
        if isinstance(mode, str):
            mode = LayoutMode(mode)
        self._apply_layout_mode(mode)

    def toggle_layout_mode(self):
        self._apply_layout_mode(self._get_next_mode())

    def focus_library(self):
        self._apply_layout_mode(LayoutMode.LIBRARY_FOCUS)

    def focus_workbench(self):
        self._apply_layout_mode(LayoutMode.WORKBENCH_FOCUS)

    def restore_split(self):
        self._apply_layout_mode(LayoutMode.SPLIT)

    @property
    def layout_mode(self) -> str:
        return self._layout_mode.value

    def add_left_widget(self, widget: QWidget, name: str):
        self.left_panel.content.addWidget(widget)

    def add_center_tab(self, widget: QWidget, title: str):
        self.center_tabs.addTab(widget, title)

    def collapse_left(self):
        self.focus_workbench()

    def expand_left(self):
        self.restore_split()
