"""
项目管理页面 - 连接到后端 ProjectManager
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy,
    QFileDialog, QMessageBox, QFrame
)

from qfluentwidgets import (
    PrimaryPushButton, PushButton, FluentIcon, CardWidget, TitleLabel,
    SubtitleLabel, BodyLabel, CaptionLabel, IconWidget,
    TransparentToolButton, ElevatedCardWidget, InfoBar, InfoBarPosition,
    LineEdit, TextEdit, MessageBox, Dialog, ScrollArea, SearchLineEdit,
    ProgressBar, ComboBox
)

from transcriptionist_v3.core.config import get_config
from transcriptionist_v3.domain.models.project import Project
from transcriptionist_v3.application.project_manager import ProjectManager, ProjectExporter

logger = logging.getLogger(__name__)


class ProjectCard(ElevatedCardWidget):
    """项目卡片"""
    clicked = Signal(object)  # Project
    edit_clicked = Signal(object)  # Project
    delete_clicked = Signal(object)  # Project
    export_clicked = Signal(object)  # Project
    
    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self.setFixedHeight(60) # Compact height
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._init_ui()
    
    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8) # Compact margins
        layout.setSpacing(10)
        
        # 图标
        icon = IconWidget(FluentIcon.FOLDER)
        icon.setFixedSize(40, 40)
        layout.addWidget(icon)
        
        # 信息区域
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        
        # 名称
        name_label = SubtitleLabel(self.project.name)
        name_label.setStyleSheet("background: transparent;")
        info_layout.addWidget(name_label)
        
        
        # 描述（如果有）- Compact Mode: Hide description
        # if self.project.description:
        #     desc = self.project.description[:60] + ('...' if len(self.project.description) > 60 else '')
        #     desc_label = CaptionLabel(desc)
        #     desc_label.setStyleSheet("color: #666; background: transparent;")
        #     info_layout.addWidget(desc_label)
        
        # 元数据
        modified_str = ""
        if self.project.modified_at:
            modified_str = self.project.modified_at.strftime("%Y-%m-%d") # Short date
        # Compact Mode: simpler text
        meta_label = CaptionLabel(f"{self.project.file_count} 文件 · {modified_str}")
        meta_label.setStyleSheet("color: #888; background: transparent;")
        info_layout.addWidget(meta_label)
        
        layout.addLayout(info_layout, 1)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)
        
        # 导出按钮
        export_btn = TransparentToolButton(FluentIcon.SHARE)
        export_btn.setFixedSize(32, 32)
        export_btn.setToolTip("导出项目")
        export_btn.clicked.connect(lambda: self.export_clicked.emit(self.project))
        btn_layout.addWidget(export_btn)
        
        # 编辑按钮
        edit_btn = TransparentToolButton(FluentIcon.EDIT)
        edit_btn.setFixedSize(32, 32)
        edit_btn.setToolTip("编辑项目")
        edit_btn.clicked.connect(lambda: self.edit_clicked.emit(self.project))
        btn_layout.addWidget(edit_btn)
        
        # 删除按钮
        delete_btn = TransparentToolButton(FluentIcon.DELETE)
        delete_btn.setFixedSize(32, 32)
        delete_btn.setToolTip("删除项目")
        delete_btn.clicked.connect(lambda: self.delete_clicked.emit(self.project))
        btn_layout.addWidget(delete_btn)
        
        # 打开按钮
        open_btn = TransparentToolButton(FluentIcon.CHEVRON_RIGHT)
        open_btn.setFixedSize(32, 32)
        open_btn.setToolTip("打开项目")
        open_btn.clicked.connect(lambda: self.clicked.emit(self.project))
        btn_layout.addWidget(open_btn)
        
        layout.addLayout(btn_layout)
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.project)
        super().mouseReleaseEvent(event)


class CreateProjectDialog(MessageBox):
    """创建项目对话框"""
    
    def __init__(self, parent=None, project: Optional[Project] = None):
        self.is_edit = project is not None
        title = "编辑项目" if self.is_edit else "新建项目"
        super().__init__(title, "", parent)
        
        self.project = project
        self._init_content()
    
    def _init_content(self):
        # 移除默认内容
        self.textLayout.removeWidget(self.contentLabel)
        self.contentLabel.hide()
        
        # 名称输入
        name_label = BodyLabel("项目名称:")
        self.textLayout.addWidget(name_label)
        
        self.name_edit = LineEdit()
        self.name_edit.setPlaceholderText("输入项目名称")
        if self.project:
            self.name_edit.setText(self.project.name)
        self.textLayout.addWidget(self.name_edit)
        
        # 描述输入
        desc_label = BodyLabel("项目描述:")
        self.textLayout.addWidget(desc_label)
        
        self.desc_edit = TextEdit()
        self.desc_edit.setPlaceholderText("输入项目描述（可选）")
        self.desc_edit.setFixedHeight(80)
        if self.project and self.project.description:
            self.desc_edit.setPlainText(self.project.description)
        self.textLayout.addWidget(self.desc_edit)
        
        # 更新按钮文字
        self.yesButton.setText("保存" if self.is_edit else "创建")
        self.cancelButton.setText("取消")
    
    def get_data(self):
        """获取输入数据"""
        return {
            'name': self.name_edit.text().strip(),
            'description': self.desc_edit.toPlainText().strip()
        }


class ProjectsPage(QWidget):
    """项目管理页面"""
    
    # 信号
    project_opened = Signal(object)  # Project
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("projectsPage")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # 初始化项目管理器
        self._init_manager()
        
        # 项目卡片列表
        self._project_cards: List[ProjectCard] = []
        
        self._init_ui()
        self._load_projects()
    
    def _init_manager(self):
        """初始化项目管理器"""
        try:
            projects_dir = Path(get_config('projects_dir', './data/projects'))
            projects_dir.mkdir(parents=True, exist_ok=True)
            self._manager = ProjectManager(projects_dir)
            logger.info(f"ProjectManager initialized: {projects_dir}")
        except Exception as e:
            logger.error(f"Failed to init ProjectManager: {e}")
            self._manager = None
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        # Compact Mode: reduce margins significantly
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 标题栏 - Compact Mode: Hide large title
        header = QHBoxLayout()
        header.setContentsMargins(4, 0, 4, 0)
        
        # title = TitleLabel("项目管理")
        # header.addWidget(title)
        
        # header.addStretch()
        
        # 搜索框 - Allow expanding to fill width
        self.search_edit = SearchLineEdit()
        self.search_edit.setPlaceholderText("搜索项目...")
        # self.search_edit.setFixedWidth(200) # Remove fixed width
        self.search_edit.textChanged.connect(self._on_search)
        header.addWidget(self.search_edit, 1) # Expand
        
        # 新建按钮
        new_btn = PrimaryPushButton(FluentIcon.ADD, "新建项目")
        new_btn.clicked.connect(self._on_create_project)
        header.addWidget(new_btn)
        
        layout.addLayout(header)
        
        layout.addLayout(header)
        
        # 描述 - Compact Mode: Hide
        # desc = CaptionLabel("管理您的音效项目，组织和导出音效文件")
        # desc.setStyleSheet("color: #666; background: transparent;")
        # layout.addWidget(desc)
        
        # 统计信息卡片 - Compact Mode: Hide to save space
        # stats_card = CardWidget()
        # stats_layout = QHBoxLayout(stats_card)
        # stats_layout.setContentsMargins(20, 16, 20, 16)
        # stats_layout.setSpacing(40)
        
        # # 项目数
        # self.total_projects_label = self._create_stat_item("项目总数", "0")
        # stats_layout.addWidget(self.total_projects_label)
        
        # # 文件数
        # self.total_files_label = self._create_stat_item("文件总数", "0")
        # stats_layout.addWidget(self.total_files_label)
        
        # stats_layout.addStretch()
        # layout.addWidget(stats_card)
        
        # 项目列表区域 - Flat Design: No CardWidget wrapper
        
        # 列表标题
        list_header = QHBoxLayout()
        list_header.setContentsMargins(4, 0, 4, 0) # Align with header
        self.list_title = SubtitleLabel("所有项目")
        self.list_title.setStyleSheet("background: transparent;")
        list_header.addWidget(self.list_title)
        list_header.addStretch()
        
        # 刷新按钮
        refresh_btn = TransparentToolButton(FluentIcon.SYNC)
        refresh_btn.setToolTip("刷新")
        refresh_btn.clicked.connect(self._load_projects)
        list_header.addWidget(refresh_btn)
        
        layout.addLayout(list_header)
        
        # 滚动区域
        self.scroll_area = ScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame) # Seamless
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        
        self.projects_container = QWidget()
        self.projects_container.setStyleSheet("background: transparent;")
        self.projects_layout = QVBoxLayout(self.projects_container)
        self.projects_layout.setContentsMargins(0, 0, 0, 0)
        self.projects_layout.setSpacing(8)
        
        # 空状态
        self.empty_label = CaptionLabel("暂无项目\n\n点击「新建项目」创建您的第一个项目")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #888; padding: 60px; background: transparent;")
        self.projects_layout.addWidget(self.empty_label)
        self.projects_layout.addStretch()
        
        self.scroll_area.setWidget(self.projects_container)
        layout.addWidget(self.scroll_area, 1)
    
    def _create_stat_item(self, label: str, value: str) -> QWidget:
        """创建统计项"""
        widget = QWidget()
        widget.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        value_label = SubtitleLabel(value)
        value_label.setObjectName("statValue")
        value_label.setStyleSheet("background: transparent;")
        layout.addWidget(value_label)
        
        name_label = CaptionLabel(label)
        name_label.setStyleSheet("color: #666; background: transparent;")
        layout.addWidget(name_label)
        
        return widget
    
    def _load_projects(self):
        """加载项目列表"""
        if not self._manager:
            return
        
        # 清空现有卡片
        for card in self._project_cards:
            card.deleteLater()
        self._project_cards.clear()
        
        # 获取所有项目
        projects = self._manager.get_all_projects()
        
        # 更新统计
        
        
        # 显示/隐藏空状态
        self.empty_label.setVisible(len(projects) == 0)
        
        if not projects:
            self.list_title.setText("所有项目")
            return
        
        self.list_title.setText(f"所有项目 ({len(projects)})")
        
        # 按修改时间排序
        projects.sort(key=lambda p: p.modified_at or datetime.min, reverse=True)
        
        # 创建项目卡片
        for project in projects:
            card = ProjectCard(project)
            card.clicked.connect(self._on_project_clicked)
            card.edit_clicked.connect(self._on_edit_project)
            card.delete_clicked.connect(self._on_delete_project)
            card.export_clicked.connect(self._on_export_project)
            self._project_cards.append(card)
            # 插入到 stretch 之前
            self.projects_layout.insertWidget(self.projects_layout.count() - 1, card)
    
    def _update_stat_value(self, widget: QWidget, value: str):
        """更新统计值"""
        value_label = widget.findChild(SubtitleLabel, "statValue")
        if value_label:
            value_label.setText(value)
    
    def _on_search(self, text: str):
        """搜索项目"""
        query = text.strip().lower()
        
        for card in self._project_cards:
            if not query:
                card.setVisible(True)
            else:
                name_match = query in card.project.name.lower()
                desc_match = query in (card.project.description or '').lower()
                card.setVisible(name_match or desc_match)
    
    def _on_create_project(self):
        """创建新项目"""
        if not self._manager:
            InfoBar.error(
                title="错误",
                content="项目管理器未初始化",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000
            )
            return
        
        dialog = CreateProjectDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            if not data['name']:
                InfoBar.warning(
                    title="提示",
                    content="请输入项目名称",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2000
                )
                return
            
            try:
                project = self._manager.create_project(
                    name=data['name'],
                    description=data['description']
                )
                InfoBar.success(
                    title="成功",
                    content=f"项目「{project.name}」已创建",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2000
                )
                self._load_projects()
            except ValueError as e:
                InfoBar.error(
                    title="创建失败",
                    content=str(e),
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000
                )
    
    def _on_edit_project(self, project: Project):
        """编辑项目"""
        if not self._manager:
            return
        
        dialog = CreateProjectDialog(self, project)
        if dialog.exec():
            data = dialog.get_data()
            if not data['name']:
                InfoBar.warning(
                    title="提示",
                    content="请输入项目名称",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2000
                )
                return
            
            try:
                self._manager.update_project(
                    project.id,
                    name=data['name'],
                    description=data['description']
                )
                InfoBar.success(
                    title="成功",
                    content="项目已更新",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2000
                )
                self._load_projects()
            except ValueError as e:
                InfoBar.error(
                    title="更新失败",
                    content=str(e),
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000
                )
    
    def _on_delete_project(self, project: Project):
        """删除项目"""
        if not self._manager:
            return
        
        # 确认对话框
        msg = MessageBox(
            "确认删除",
            f"确定要删除项目「{project.name}」吗？\n\n此操作不会删除项目中的音效文件。",
            self
        )
        msg.yesButton.setText("删除")
        msg.cancelButton.setText("取消")
        
        if msg.exec():
            if self._manager.delete_project(project.id):
                InfoBar.success(
                    title="成功",
                    content=f"项目「{project.name}」已删除",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=2000
                )
                self._load_projects()
            else:
                InfoBar.error(
                    title="删除失败",
                    content="无法删除项目",
                    parent=self,
                    position=InfoBarPosition.TOP,
                    duration=3000
                )
    
    def _on_export_project(self, project: Project):
        """导出项目"""
        # 选择导出目录
        export_dir = QFileDialog.getExistingDirectory(
            self,
            "选择导出目录",
            "",
            QFileDialog.Option.ShowDirsOnly
        )
        
        if not export_dir:
            return
        
        # TODO: 实现完整的导出功能，需要获取项目中的文件列表
        # 目前项目只存储 file_ids，需要从 library 获取实际文件
        InfoBar.info(
            title="导出功能",
            content=f"导出到: {export_dir}\n（完整导出功能开发中）",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=3000
        )
    
    def _on_project_clicked(self, project: Project):
        """打开项目"""
        self.project_opened.emit(project)
        InfoBar.info(
            title="打开项目",
            content=f"打开项目: {project.name}",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=2000
        )
