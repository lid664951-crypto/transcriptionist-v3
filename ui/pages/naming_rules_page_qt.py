"""
命名规则页面 - 完整功能版本
支持：术语库管理、UCS Excel导入、命名模板、清洗规则
集成后端：TemplateManager, NamingValidator, UCSParser
"""

import csv
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal, QThread, QObject
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog,
    QHeaderView, QAbstractItemView, QTableWidgetItem
)

from qfluentwidgets import (
    PushButton, PrimaryPushButton, ComboBox, LineEdit,
    FluentIcon, CardWidget, TitleLabel, SubtitleLabel,
    BodyLabel, CaptionLabel, ListWidget,
    TransparentToolButton, TableWidget, SwitchButton,
    SegmentedWidget, IconWidget, TextEdit, ProgressBar, isDarkTheme
)

# Architecture refactoring: use centralized utilities and services
from transcriptionist_v3.ui.utils.notifications import NotificationHelper
from transcriptionist_v3.ui.utils.workers import cleanup_thread
from transcriptionist_v3.ui.workers.naming_workers import GlossaryLoadWorker
from transcriptionist_v3.application.naming_manager.glossary import GlossaryManager
from transcriptionist_v3.application.naming_manager.cleaning import CleaningManager, CleaningRule
from transcriptionist_v3.ui.themes.theme_tokens import get_theme_tokens

logger = logging.getLogger(__name__)

class NamingRulesPage(QWidget):
    """命名规则页面 - 完整功能"""
    
    glossary_updated = Signal(dict)  # 术语库更新信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("namingRulesPage")
        
        self._glossary_manager = GlossaryManager.instance()
        self._cleaning_manager = CleaningManager.instance()
        self._template_manager = None
        
        self._current_tab = "glossary"
        self._load_thread: Optional[QThread] = None
        self._load_worker: Optional[GlossaryLoadWorker] = None
        
        # 分页状态
        self._current_page = 0
        self._page_size = 50
        self._filtered_glossary_list = []  # 缓存过滤后的转换列表 [(en, zh), ...]
        
        self._init_backend()
        self._init_ui()
        self._apply_theme_tokens()
        self._update_glossary_table()  # 初始加载表格

    def _apply_theme_tokens(self):
        tokens = get_theme_tokens(isDarkTheme())
        self.setStyleSheet(
            f"""
QWidget#namingRulesPage {{
    background-color: {tokens.window_bg};
}}

QWidget#namingRulesPage TitleLabel,
QWidget#namingRulesPage SubtitleLabel,
QWidget#namingRulesPage BodyLabel {{
    color: {tokens.text_primary};
    background: transparent;
}}

QWidget#namingRulesPage CaptionLabel {{
    color: {tokens.text_muted};
    background: transparent;
}}

QWidget#namingRulesPage SwitchButton,
QWidget#namingRulesPage SwitchButton QLabel,
QWidget#namingRulesPage ListWidget,
QWidget#namingRulesPage QTableWidget,
QWidget#namingRulesPage TableWidget,
QWidget#namingRulesPage QTableWidget QLabel,
QWidget#namingRulesPage TableWidget QLabel {{
    color: {tokens.text_muted};
}}

QWidget#namingRulesPage BodyLabel,
QWidget#namingRulesPage SubtitleLabel,
QWidget#namingRulesPage TitleLabel {{
    color: {tokens.text_primary};
}}

QWidget#namingRulesPage CardWidget {{
    background-color: {tokens.surface_0};
    border: 1px solid {tokens.border};
    border-radius: 12px;
}}

QWidget#namingRulesPage SegmentedWidget,
QWidget#namingRulesPage QListWidget,
QWidget#namingRulesPage QTableWidget,
QWidget#namingRulesPage TableWidget,
QWidget#namingRulesPage TextEdit,
QWidget#namingRulesPage LineEdit,
QWidget#namingRulesPage ComboBox {{
    background-color: {tokens.surface_0};
    color: {tokens.text_primary};
    border: 1px solid {tokens.border};
    border-radius: 8px;
}}

QWidget#namingRulesPage QHeaderView::section {{
    background-color: {tokens.surface_1};
    color: {tokens.text_secondary};
    border: none;
    border-bottom: 1px solid {tokens.border};
    padding: 7px 8px;
    font-weight: 600;
}}

QWidget#namingRulesPage QScrollBar:vertical,
QWidget#namingRulesPage QScrollBar:horizontal {{
    background: transparent;
}}

QWidget#namingRulesPage QScrollBar::handle:vertical,
QWidget#namingRulesPage QScrollBar::handle:horizontal {{
    background: {tokens.border_soft};
    border-radius: 6px;
}}
"""
        )
    
    def _init_backend(self):
        """初始化后端服务"""
        try:
            from transcriptionist_v3.application.naming_manager.templates import TemplateManager
            from transcriptionist_v3.runtime.runtime_config import get_data_dir
            # 使用 runtime_config 获取数据目录
            data_dir = get_data_dir()
            self._template_manager = TemplateManager.instance(str(data_dir))
            logger.info("TemplateManager initialized")
        except Exception as e:
            logger.warning(f"Failed to init TemplateManager: {e}")
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        
        # 标题
        title = TitleLabel("命名规则")
        layout.addWidget(title)
        
        # Tab切换
        self.tab_widget = SegmentedWidget()
        # 术语库功能暂移除
        # self.tab_widget.addItem("glossary", "术语库")
        self.tab_widget.addItem("naming", "命名模板")
        self.tab_widget.addItem("cleaning", "清洗规则")
        self.tab_widget.currentItemChanged.connect(self._on_tab_changed)
        self.tab_widget.setCurrentItem("naming") # 默认选命名
        layout.addWidget(self.tab_widget)
        
        # 内容区域 - 使用 QStackedWidget
        from PySide6.QtWidgets import QStackedWidget
        self.content_stack = QStackedWidget()
        
        # 创建各个Tab内容
        self.glossary_widget = self._create_glossary_tab()
        self.naming_widget = self._create_naming_tab()
        self.cleaning_widget = self._create_cleaning_tab()
        
        self.content_stack.addWidget(self.glossary_widget)
        self.content_stack.addWidget(self.naming_widget)
        self.content_stack.addWidget(self.cleaning_widget)
        
        self.content_stack.setCurrentIndex(1)  # 默认显示命名模板
        layout.addWidget(self.content_stack, 1)
    
    def _on_tab_changed(self, key: str):
        """Tab切换"""
        self._current_tab = key
        # Safety check: content_stack may not be initialized yet during UI setup
        if not hasattr(self, 'content_stack'):
            return
        
        # 切换到对应的widget
        if key == "glossary":
            self.content_stack.setCurrentIndex(0)
        elif key == "naming":
            self.content_stack.setCurrentIndex(1)
        elif key == "cleaning":
            self.content_stack.setCurrentIndex(2)

    def _create_glossary_tab(self) -> QWidget:
        """创建术语库Tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        # 工具栏
        toolbar = QHBoxLayout()
        
        import_csv_btn = PushButton(FluentIcon.DOCUMENT, "导入CSV")
        import_csv_btn.clicked.connect(self._on_import_csv)
        toolbar.addWidget(import_csv_btn)
        
        import_excel_btn = PushButton(FluentIcon.DOWNLOAD, "导入UCS Excel")
        import_excel_btn.clicked.connect(self._on_import_ucs_excel)
        toolbar.addWidget(import_excel_btn)
        
        export_btn = PushButton(FluentIcon.SAVE, "导出CSV")
        export_btn.clicked.connect(self._on_export_csv)
        toolbar.addWidget(export_btn)
        
        clear_btn = PushButton(FluentIcon.DELETE, "清空")
        clear_btn.clicked.connect(self._on_clear_glossary)
        toolbar.addWidget(clear_btn)
        
        toolbar.addStretch()
        
        self.glossary_count_label = CaptionLabel("共 0 条术语")
        toolbar.addWidget(self.glossary_count_label)
        
        layout.addLayout(toolbar)
        
        # 搜索框
        search_row = QHBoxLayout()
        self.glossary_search = LineEdit()
        self.glossary_search.setPlaceholderText("搜索术语...")
        self.glossary_search.textChanged.connect(self._on_search_glossary)
        search_row.addWidget(self.glossary_search)
        layout.addLayout(search_row)
        
        # 术语表格
        self.glossary_table = TableWidget()
        self.glossary_table.setColumnCount(3)
        self.glossary_table.setHorizontalHeaderLabels(["英文", "中文", "操作"])
        self.glossary_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.glossary_table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.glossary_table.cellChanged.connect(self._on_glossary_cell_changed)
        
        header = self.glossary_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.glossary_table.setColumnWidth(2, 60)
        
        layout.addWidget(self.glossary_table, 1)
    
        # 分页控制栏
        pagination_layout = QHBoxLayout()
        pagination_layout.addStretch()
        
        self.prev_btn = TransparentToolButton(FluentIcon.LEFT_ARROW)
        self.prev_btn.clicked.connect(self._on_prev_page)
        pagination_layout.addWidget(self.prev_btn)
        
        self.page_label = CaptionLabel("第 1 页")
        pagination_layout.addWidget(self.page_label)
        
        self.next_btn = TransparentToolButton(FluentIcon.RIGHT_ARROW)
        self.next_btn.clicked.connect(self._on_next_page)
        pagination_layout.addWidget(self.next_btn)
        
        pagination_layout.addStretch()
        layout.addLayout(pagination_layout)
        
        # 添加术语
        add_row = QHBoxLayout()
        
        self.en_edit = LineEdit()
        self.en_edit.setPlaceholderText("英文术语")
        add_row.addWidget(self.en_edit)
        
        self.cn_edit = LineEdit()
        self.cn_edit.setPlaceholderText("中文翻译")
        add_row.addWidget(self.cn_edit)
        
        add_btn = PrimaryPushButton(FluentIcon.ADD, "添加")
        add_btn.setFixedWidth(80)
        add_btn.clicked.connect(self._on_add_term)
        add_row.addWidget(add_btn)
        
        layout.addLayout(add_row)
        
        return widget

    def _create_naming_tab(self) -> QWidget:
        """创建命名模板Tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        
        desc = CaptionLabel("设置翻译后的文件名格式，支持变量替换")
        layout.addWidget(desc)
        
        presets_card = CardWidget()
        presets_layout = QVBoxLayout(presets_card)
        presets_layout.setContentsMargins(16, 16, 16, 16)
        presets_layout.setSpacing(12)
        
        presets_title = SubtitleLabel("内置模板")
        presets_layout.addWidget(presets_title)
        
        self._template_switches = {}
        templates = []
        
        if self._template_manager:
            try:
                templates = self._template_manager.get_builtin_templates()
            except Exception as e:
                logger.error(f"Failed to get builtin templates: {e}")
        
        if not templates:
            # Fallback: hardcoded 4 templates if manager fails
            templates_data = [
                ("ucs_standard", "UCS标准命名", "{category}_{subcategory}_{translated}_{index:02}"),
                ("bilingual", "中英双语", "【{translated}】{filename}"),
                ("numbered", "序号命名", "{translated}_{index:02}"),
                ("translated_only", "仅译名", "{translated}"),
            ]
            for id, name, pattern in templates_data:
                row = self._create_template_row(id, name, pattern)
                presets_layout.addLayout(row)
        else:
            for template in templates:
                row = self._create_template_row(template.id, template.name, template.pattern)
                presets_layout.addLayout(row)
        
        
        # 移除自定义格式区域，保持界面简洁，但保留预览功能
        layout.addWidget(presets_card)
        
        # 预览区域
        preview_card = CardWidget()
        preview_layout = QHBoxLayout(preview_card)
        preview_layout.setContentsMargins(16, 12, 16, 12)
        
        preview_title = CaptionLabel("效果预览:")
        preview_layout.addWidget(preview_title)
        
        self.preview_label = BodyLabel("木质脚步_01.wav → 【木头脚步声】木质脚步_01.wav")
        self.preview_label.setTextColor(Qt.GlobalColor.gray)
        preview_layout.addWidget(self.preview_label, 1)
        
        layout.addWidget(preview_card)
        layout.addStretch()
        
        # 初始刷新一下预览
        self._on_test_template()
        
        return widget
    
    def _create_template_row(self, id: str, name: str, pattern: str) -> QHBoxLayout:
        """创建模板行"""
        row = QHBoxLayout()
        row.setSpacing(12)
        
        switch = SwitchButton()
        # 从TemplateManager同步状态
        active_id = self._template_manager.active_template_id if self._template_manager else "translated_only"
        switch.setChecked(id == active_id)
        switch.checkedChanged.connect(lambda checked, i=id: self._on_template_toggled(i, checked))
        self._template_switches[id] = switch
        row.addWidget(switch)
        
        # 创建一个容器widget来包含垂直布局
        info_widget = QWidget()
        info_widget.setStyleSheet("background: transparent")
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)
        
        name_label = BodyLabel(name)
        name_label.setStyleSheet("background: transparent")
        info_layout.addWidget(name_label)
        
        pattern_label = CaptionLabel(f"格式: {pattern}")
        pattern_label.setStyleSheet("background: transparent")
        info_layout.addWidget(pattern_label)
        
        row.addWidget(info_widget, 1)
        
        return row

    def _create_cleaning_tab(self) -> QWidget:
        """创建清洗规则Tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        
        desc = CaptionLabel("在翻译前清理文件名中的无用内容")
        layout.addWidget(desc)
        
        rules_card = CardWidget()
        rules_layout = QVBoxLayout(rules_card)
        rules_layout.setContentsMargins(16, 16, 16, 16)
        rules_layout.setSpacing(12)
        
        rules_title = SubtitleLabel("清洗规则")
        rules_layout.addWidget(rules_title)
        
        self._rule_switches = {}
        for rule in self._cleaning_manager.get_rules():
            row = QHBoxLayout()
            row.setSpacing(12)
            
            switch = SwitchButton()
            switch.setChecked(rule.enabled)
            switch.checkedChanged.connect(lambda checked, r=rule: self._on_rule_toggled(r.id, checked))
            self._rule_switches[rule.id] = switch
            row.addWidget(switch)
            
            # 创建一个容器widget来包含垂直布局
            info_widget = QWidget()
            info_widget.setStyleSheet("background: transparent")
            info_layout = QVBoxLayout(info_widget)
            info_layout.setContentsMargins(0, 0, 0, 0)
            info_layout.setSpacing(4)
            
            name_label = BodyLabel(rule.name)
            name_label.setStyleSheet("background: transparent")
            info_layout.addWidget(name_label)
            
            example_label = CaptionLabel(f"示例: {rule.description}")
            example_label.setStyleSheet("background: transparent")
            info_layout.addWidget(example_label)
            
            row.addWidget(info_widget, 1)
            
            rules_layout.addLayout(row)
        
        layout.addWidget(rules_card)
        
        # 测试清洗
        test_card = CardWidget()
        test_layout = QVBoxLayout(test_card)
        test_layout.setContentsMargins(16, 16, 16, 16)
        test_layout.setSpacing(8)
        
        test_title = SubtitleLabel("测试清洗")
        test_layout.addWidget(test_title)
        
        input_row = QHBoxLayout()
        self.clean_input = LineEdit()
        self.clean_input.setPlaceholderText("输入测试文件名...")
        self.clean_input.setText("爆炸音效(新)_[最终版]_01")
        input_row.addWidget(self.clean_input)
        
        test_btn = PushButton(FluentIcon.PLAY, "测试")
        test_btn.clicked.connect(self._on_test_cleaning)
        input_row.addWidget(test_btn)
        
        test_layout.addLayout(input_row)
        
        result_row = QHBoxLayout()
        result_label = CaptionLabel("结果:")
        result_row.addWidget(result_label)
        self.clean_result = BodyLabel("-")
        result_row.addWidget(self.clean_result, 1)
        test_layout.addLayout(result_row)
        
        layout.addWidget(test_card)
        layout.addStretch()
        
        return widget

    # ═══════════════════════════════════════════════════════════
    # 术语库功能
    # ═══════════════════════════════════════════════════════════
    
    def _update_glossary_table(self):
        """更新术语表格界面 (带分页优化)"""
        # 如果是首次加载或数据刷新，且没有过滤列表，则初始化全量列表
        if not self.glossary_search.text().strip() and not self._filtered_glossary_list:
            glossary = self._glossary_manager.get_all()
            self._filtered_glossary_list = sorted(glossary.items())
            self.glossary_count_label.setText(f"共 {len(self._filtered_glossary_list)} 条术语")

        total_items = len(self._filtered_glossary_list)
        total_pages = (total_items + self._page_size - 1) // self._page_size if total_items > 0 else 1
        
        # 修正当前页码
        if self._current_page >= total_pages:
            self._current_page = max(0, total_pages - 1)
            
        self.page_label.setText(f"第 {self._current_page + 1} / {total_pages} 页")
        self.prev_btn.setEnabled(self._current_page > 0)
        self.next_btn.setEnabled(self._current_page < total_pages - 1)

        self.glossary_table.setRowCount(0)
        self.glossary_table.blockSignals(True)
        
        # 计算当前页的数据片段
        start_idx = self._current_page * self._page_size
        end_idx = min(start_idx + self._page_size, total_items)
        page_items = self._filtered_glossary_list[start_idx:end_idx]
        
        for i, (en, zh) in enumerate(page_items):
            self.glossary_table.insertRow(i)
            self.glossary_table.setItem(i, 0, QTableWidgetItem(en))
            self.glossary_table.setItem(i, 1, QTableWidgetItem(zh))
            
            del_btn = TransparentToolButton(FluentIcon.DELETE)
            # 注意闭包 capture 问题
            del_btn.clicked.connect(lambda _, e=en: self._on_delete_term(e))
            self.glossary_table.setCellWidget(i, 2, del_btn)
            
        self.glossary_table.blockSignals(False)

    def _on_prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._update_glossary_table()

    def _on_next_page(self):
        total_items = len(self._filtered_glossary_list)
        total_pages = (total_items + self._page_size - 1) // self._page_size
        if self._current_page < total_pages - 1:
            self._current_page += 1
            self._update_glossary_table()

    def _on_import_csv(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择CSV文件", "", "CSV文件 (*.csv)")
        if file_path:
            self._start_load(file_path, 'csv')
    
    def _on_import_ucs_excel(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择UCS Excel文件", "", "Excel文件 (*.xlsx *.xls)")
        if file_path:
            self._start_load(file_path, 'excel')
    
    def _start_load(self, file_path: str, file_type: str):
        self._load_thread = QThread()
        self._load_worker = GlossaryLoadWorker(file_path, file_type)
        self._load_worker.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.finished.connect(self._on_load_finished)
        self._load_worker.error.connect(self._on_load_error)
        self._load_thread.start()
    
    def _on_load_finished(self, glossary: dict):
        cleanup_thread(self._load_thread, self._load_worker)
        self._load_thread = None
        self._load_worker = None
        
        self._glossary_manager.update(glossary)
        self._filtered_glossary_list = []  # 重置缓存强制刷新
        self._update_glossary_table()
        self.glossary_updated.emit(self._glossary_manager.get_all())
        NotificationHelper.success(self, "导入成功", f"成功导入 {len(glossary)} 条术语")
    
    def _on_load_error(self, error_msg: str):
        cleanup_thread(self._load_thread, self._load_worker)
        self._load_thread = None
        self._load_worker = None
        NotificationHelper.error(self, "导入失败", error_msg)
    
    def _on_export_csv(self):
        glossary = self._glossary_manager.get_all()
        if not glossary:
            NotificationHelper.warning(self, "提示", "术语库为空")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(self, "保存CSV文件", "glossary.csv", "CSV文件 (*.csv)")
        if file_path:
            try:
                import csv
                with open(file_path, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['英文', '中文'])
                    for en, zh in sorted(glossary.items()):
                        writer.writerow([en, zh])
                NotificationHelper.success(self, "导出成功", f"已导出 {len(glossary)} 条术语")
            except Exception as e:
                NotificationHelper.error(self, "导出失败", str(e))

    def _on_clear_glossary(self):
        self._glossary_manager.clear()
        self._filtered_glossary_list = []
        self._current_page = 0
        self._update_glossary_table()
        self.glossary_updated.emit({})
        NotificationHelper.info(self, "已清空", "术语库已清空")
    
    def _on_add_term(self):
        en = self.en_edit.text().strip()
        zh = self.cn_edit.text().strip()
        if not en or not zh:
            NotificationHelper.warning(self, "提示", "请输入英文术语和中文翻译")
            return
            
        self._glossary_manager.add_term(en, zh)
        self.en_edit.clear()
        self.cn_edit.clear()
        self._filtered_glossary_list = []  # 刷新
        self._update_glossary_table()
        self.glossary_updated.emit(self._glossary_manager.get_all())
        NotificationHelper.success(self, "添加成功", f"已添加: {en} → {zh}")

    def _on_delete_term(self, en: str):
        self._glossary_manager.remove_term(en)
        # 从本地过滤列表中也移除，避免重绘整个列表
        self._filtered_glossary_list = [item for item in self._filtered_glossary_list if item[0] != en]
        self._update_glossary_table()
        self.glossary_updated.emit(self._glossary_manager.get_all())

    def _on_search_glossary(self, text: str):
        """全局搜索优化"""
        search_text = text.lower().strip()
        all_terms = sorted(self._glossary_manager.get_all().items())
        
        if not search_text:
            self._filtered_glossary_list = all_terms
        else:
            self._filtered_glossary_list = [
                (en, zh) for en, zh in all_terms 
                if search_text in en.lower() or search_text in zh.lower()
            ]
        
        self.glossary_count_label.setText(f"找到 {len(self._filtered_glossary_list)} 条结果")
        self._current_page = 0
        self._update_glossary_table()
    
    def _on_glossary_cell_changed(self, row: int, column: int):
        if column > 1: return
        en_item = self.glossary_table.item(row, 0)
        zh_item = self.glossary_table.item(row, 1)
        if en_item and zh_item:
            self._glossary_manager.add_term(en_item.text(), zh_item.text())
            self.glossary_updated.emit(self._glossary_manager.get_all())

    # ═══════════════════════════════════════════════════════════
    # 命名模板功能
    # ═══════════════════════════════════════════════════════════
    
    def _on_test_template(self):
        if not self._template_manager:
            return
            
        pattern = self.get_active_template()
        context = self._template_manager.create_context(
            "木质脚步_01.wav",
            ucs_components={
                "category": "脚步声", 
                "subcategory": "木质", 
                "descriptor": "行走",
                "variation": "01",
                "version": "v1"
            },
            index=1,
            translated="木头脚步声_慢速"
        )
        
        from transcriptionist_v3.application.naming_manager.templates import NamingTemplate
        temp = NamingTemplate("test", "Test", pattern)
        try:
            result = temp.format(context)
            self.preview_label.setText(f"预览: 木质脚步_01.wav → {result}")
        except Exception as e:
            self.preview_label.setText(f"模板错误: {e}")
            
    def _on_template_toggled(self, template_id: str, checked: bool):
        """处理模板互斥逻辑"""
        if not checked:
            # 如果是取消勾选，不执行互斥，但也要确保至少有一个激活（或回退到自定义）
            return
            
        # 当一个模板打开时，关闭其他所有模板
        for other_id, switch in self._template_switches.items():
            if other_id != template_id:
                switch.blockSignals(True)
                switch.setChecked(False)
                switch.blockSignals(False)
        
        # 同步到 TemplateManager
        if self._template_manager:
            self._template_manager.active_template_id = template_id
        
        # 刷新预览 (直接使用当前ID，无需再次遍历UI)
        self._on_test_template()
    
    def get_active_template(self) -> str:
        """获取当前激活的模板"""
        for template_id, switch in self._template_switches.items():
            if switch.isChecked():
                if self._template_manager:
                    template = self._template_manager.get_template(template_id)
                    if template:
                        return template.pattern
        return "{translated}"
    
    # ═══════════════════════════════════════════════════════════
    # 清洗规则功能
    # ═══════════════════════════════════════════════════════════
    
    def _on_rule_toggled(self, rule_id: str, checked: bool):
        """规则开关切换"""
        self._cleaning_manager.set_rule_enabled(rule_id, checked)
    
    def _on_test_cleaning(self):
        """测试清洗"""
        text = self.clean_input.text().strip()
        if not text:
            return
        
        result = self._cleaning_manager.apply_all(text)
        self.clean_result.setText(result)
