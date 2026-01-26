"""
工具箱页面 - 连接到后端 BatchProcessor
提供格式转换、响度标准化、元数据编辑等功能
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, List, Callable

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFileDialog, QSizePolicy
)
from ..utils.flow_layout import FlowLayout

from qfluentwidgets import (
    FluentIcon, CardWidget, TitleLabel, SubtitleLabel,
    BodyLabel, CaptionLabel, IconWidget, ElevatedCardWidget,
    PrimaryPushButton, PushButton, TransparentToolButton,
    InfoBar, InfoBarPosition, ProgressBar, ComboBox,
    SpinBox, DoubleSpinBox, CheckBox, LineEdit, ScrollArea,
    MessageBox, Dialog
)

from transcriptionist_v3.application.batch_processor import (
    BatchProcessor, BatchOperation, BatchResult, BatchOperationType, BatchProgress,
    FormatConverter, ConversionOptions, AudioFormat,
    LoudnessNormalizer, NormalizationOptions, NormalizationStandard,
    BatchMetadataEditor, MetadataOperation, OperationType, MetadataField
)

logger = logging.getLogger(__name__)


class BatchWorker(QThread):
    """后台批处理线程"""
    progress = Signal(object)  # BatchProgress
    finished = Signal(object)  # BatchResult
    
    def __init__(self, processor: BatchProcessor, operation: BatchOperation):
        super().__init__()
        self.processor = processor
        self.operation = operation
    
    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            def on_progress(progress: BatchProgress):
                self.progress.emit(progress)
            
            result = loop.run_until_complete(
                self.processor.process(self.operation, on_progress)
            )
            loop.close()
            self.finished.emit(result)
        except Exception as e:
            logger.error(f"Batch processing error: {e}")
            result = BatchResult()
            result.errors.append(str(e))
            self.finished.emit(result)


class ToolCard(ElevatedCardWidget):
    """工具卡片"""
    clicked = Signal()
    
    def __init__(self, icon, title: str, description: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(200, 160)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 图标
        icon_widget = IconWidget(icon)
        icon_widget.setFixedSize(40, 40)
        layout.addWidget(icon_widget, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # 标题
        title_label = SubtitleLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("background: transparent;")
        layout.addWidget(title_label)
        
        # 描述
        desc_label = CaptionLabel(description)
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #666; background: transparent;")
        layout.addWidget(desc_label)
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class FormatConvertDialog(MessageBox):
    """格式转换对话框"""
    
    def __init__(self, parent=None):
        super().__init__("格式转换", "", parent)
        self._init_content()
    
    def _init_content(self):
        # 移除默认内容
        self.textLayout.removeWidget(self.contentLabel)
        self.contentLabel.hide()
        
        # 输出格式
        format_label = BodyLabel("输出格式:")
        self.textLayout.addWidget(format_label)
        
        self.format_combo = ComboBox()
        self.format_combo.addItems(['WAV', 'FLAC', 'MP3', 'OGG', 'M4A', 'AIFF', 'OPUS'])
        self.format_combo.setCurrentIndex(0)
        self.textLayout.addWidget(self.format_combo)
        
        # 采样率
        sr_label = BodyLabel("采样率:")
        self.textLayout.addWidget(sr_label)
        
        self.sr_combo = ComboBox()
        self.sr_combo.addItems(['保持原样', '44100 Hz', '48000 Hz', '96000 Hz'])
        self.sr_combo.setCurrentIndex(0)
        self.textLayout.addWidget(self.sr_combo)
        
        # 比特率（MP3/OGG）
        br_label = BodyLabel("比特率 (MP3/OGG):")
        self.textLayout.addWidget(br_label)
        
        self.br_combo = ComboBox()
        self.br_combo.addItems(['128k', '192k', '256k', '320k'])
        self.br_combo.setCurrentIndex(3)
        self.textLayout.addWidget(self.br_combo)
        
        # 覆盖选项
        self.overwrite_check = CheckBox("覆盖已存在的文件")
        self.textLayout.addWidget(self.overwrite_check)
        
        self.yesButton.setText("开始转换")
        self.cancelButton.setText("取消")
    
    def get_options(self) -> ConversionOptions:
        """获取转换选项"""
        format_map = {
            'WAV': AudioFormat.WAV,
            'FLAC': AudioFormat.FLAC,
            'MP3': AudioFormat.MP3,
            'OGG': AudioFormat.OGG,
            'M4A': AudioFormat.M4A,
            'AIFF': AudioFormat.AIFF,
            'OPUS': AudioFormat.OPUS,
        }
        
        sr_map = {
            '保持原样': None,
            '44100 Hz': 44100,
            '48000 Hz': 48000,
            '96000 Hz': 96000,
        }
        
        return ConversionOptions(
            output_format=format_map.get(self.format_combo.currentText(), AudioFormat.WAV),
            sample_rate=sr_map.get(self.sr_combo.currentText()),
            bitrate=self.br_combo.currentText(),
            overwrite=self.overwrite_check.isChecked(),
        )


class NormalizeDialog(MessageBox):
    """响度标准化对话框"""
    
    def __init__(self, parent=None):
        super().__init__("响度标准化", "", parent)
        self._init_content()
    
    def _init_content(self):
        self.textLayout.removeWidget(self.contentLabel)
        self.contentLabel.hide()
        
        # 标准选择
        std_label = BodyLabel("响度标准:")
        self.textLayout.addWidget(std_label)
        
        self.std_combo = ComboBox()
        self.std_combo.addItems([
            'EBU R128 (-23 LUFS) - 广播标准',
            'ATSC A/85 (-24 LUFS) - 美国广播',
            '流媒体 (-14 LUFS) - Spotify/YouTube',
            '自定义'
        ])
        self.std_combo.setCurrentIndex(0)
        self.std_combo.currentIndexChanged.connect(self._on_std_changed)
        self.textLayout.addWidget(self.std_combo)
        
        # 自定义响度
        custom_row = QHBoxLayout()
        self.custom_label = BodyLabel("目标响度 (LUFS):")
        custom_row.addWidget(self.custom_label)
        
        self.custom_spin = DoubleSpinBox()
        self.custom_spin.setRange(-60, 0)
        self.custom_spin.setValue(-23)
        self.custom_spin.setEnabled(False)
        custom_row.addWidget(self.custom_spin)
        self.textLayout.addLayout(custom_row)
        
        # 峰值限制
        peak_row = QHBoxLayout()
        peak_label = BodyLabel("峰值限制 (dBTP):")
        peak_row.addWidget(peak_label)
        
        self.peak_spin = DoubleSpinBox()
        self.peak_spin.setRange(-10, 0)
        self.peak_spin.setValue(-1)
        peak_row.addWidget(self.peak_spin)
        self.textLayout.addLayout(peak_row)
        
        # 应用限制器
        self.limiter_check = CheckBox("应用峰值限制器")
        self.limiter_check.setChecked(True)
        self.textLayout.addWidget(self.limiter_check)
        
        self.yesButton.setText("开始标准化")
        self.cancelButton.setText("取消")
    
    def _on_std_changed(self, index: int):
        self.custom_spin.setEnabled(index == 3)
    
    def get_options(self) -> NormalizationOptions:
        """获取标准化选项"""
        std_map = {
            0: NormalizationStandard.EBU_R128,
            1: NormalizationStandard.ATSC_A85,
            2: NormalizationStandard.STREAMING,
            3: NormalizationStandard.CUSTOM,
        }
        
        return NormalizationOptions(
            standard=std_map.get(self.std_combo.currentIndex(), NormalizationStandard.EBU_R128),
            target_loudness=self.custom_spin.value(),
            peak_limit=self.peak_spin.value(),
            apply_limiter=self.limiter_check.isChecked(),
        )


class MetadataEditDialog(MessageBox):
    """元数据编辑对话框"""
    
    def __init__(self, parent=None):
        super().__init__("批量编辑元数据", "", parent)
        self._init_content()
    
    def _init_content(self):
        self.textLayout.removeWidget(self.contentLabel)
        self.contentLabel.hide()
        
        # 操作类型
        op_label = BodyLabel("操作类型:")
        self.textLayout.addWidget(op_label)
        
        self.op_combo = ComboBox()
        self.op_combo.addItems(['设置值', '追加', '前置', '查找替换', '清空'])
        self.op_combo.currentIndexChanged.connect(self._on_op_changed)
        self.textLayout.addWidget(self.op_combo)
        
        # 字段选择
        field_label = BodyLabel("元数据字段:")
        self.textLayout.addWidget(field_label)
        
        self.field_combo = ComboBox()
        self.field_combo.addItems([
            '标题 (title)', '艺术家 (artist)', '专辑 (album)',
            '流派 (genre)', '年份 (year)', '注释 (comment)',
            '描述 (description)', '版权 (copyright)'
        ])
        self.textLayout.addWidget(self.field_combo)
        
        # 值输入
        self.value_label = BodyLabel("值:")
        self.textLayout.addWidget(self.value_label)
        
        self.value_edit = LineEdit()
        self.value_edit.setPlaceholderText("输入要设置的值")
        self.textLayout.addWidget(self.value_edit)
        
        # 查找替换（仅在查找替换模式显示）
        self.find_label = BodyLabel("查找:")
        self.find_label.setVisible(False)
        self.textLayout.addWidget(self.find_label)
        
        self.find_edit = LineEdit()
        self.find_edit.setPlaceholderText("要查找的文本")
        self.find_edit.setVisible(False)
        self.textLayout.addWidget(self.find_edit)
        
        self.replace_label = BodyLabel("替换为:")
        self.replace_label.setVisible(False)
        self.textLayout.addWidget(self.replace_label)
        
        self.replace_edit = LineEdit()
        self.replace_edit.setPlaceholderText("替换后的文本")
        self.replace_edit.setVisible(False)
        self.textLayout.addWidget(self.replace_edit)
        
        self.yesButton.setText("应用")
        self.cancelButton.setText("取消")
    
    def _on_op_changed(self, index: int):
        is_replace = index == 3
        is_clear = index == 4
        
        self.value_label.setVisible(not is_replace and not is_clear)
        self.value_edit.setVisible(not is_replace and not is_clear)
        self.find_label.setVisible(is_replace)
        self.find_edit.setVisible(is_replace)
        self.replace_label.setVisible(is_replace)
        self.replace_edit.setVisible(is_replace)
    
    def get_operations(self) -> List[MetadataOperation]:
        """获取元数据操作"""
        op_map = {
            0: OperationType.SET,
            1: OperationType.APPEND,
            2: OperationType.PREPEND,
            3: OperationType.REPLACE,
            4: OperationType.CLEAR,
        }
        
        field_map = {
            0: MetadataField.TITLE,
            1: MetadataField.ARTIST,
            2: MetadataField.ALBUM,
            3: MetadataField.GENRE,
            4: MetadataField.YEAR,
            5: MetadataField.COMMENT,
            6: MetadataField.DESCRIPTION,
            7: MetadataField.COPYRIGHT,
        }
        
        op_type = op_map.get(self.op_combo.currentIndex(), OperationType.SET)
        field = field_map.get(self.field_combo.currentIndex(), MetadataField.TITLE)
        
        operation = MetadataOperation(
            operation=op_type,
            field=field,
            value=self.value_edit.text(),
            find=self.find_edit.text(),
            replace_with=self.replace_edit.text(),
        )
        
        return [operation]


class ToolboxPage(QWidget):
    """工具箱页面"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolboxPage")
        
        # 初始化处理器
        self._processor = BatchProcessor()
        self._worker: Optional[BatchWorker] = None
        self._selected_files: List[Path] = []
        
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(20)
        
        # 标题
        title = TitleLabel("工具箱")
        layout.addWidget(title)
        
        desc = CaptionLabel("实用的音效批处理工具")
        desc.setStyleSheet("color: #666;")
        layout.addWidget(desc)
        
        # 文件选择区域
        file_card = CardWidget()
        file_layout = QVBoxLayout(file_card)
        file_layout.setContentsMargins(20, 16, 20, 16)
        file_layout.setSpacing(12)
        
        file_header = QHBoxLayout()
        file_title = SubtitleLabel("选择文件")
        file_header.addWidget(file_title)
        file_header.addStretch()
        
        self.file_count_label = CaptionLabel("已选择 0 个文件")
        self.file_count_label.setStyleSheet("color: #666;")
        file_header.addWidget(self.file_count_label)
        file_layout.addLayout(file_header)
        
        btn_row = QHBoxLayout()
        
        select_files_btn = PrimaryPushButton(FluentIcon.FOLDER_ADD, "选择文件")
        select_files_btn.clicked.connect(self._on_select_files)
        btn_row.addWidget(select_files_btn)
        
        select_folder_btn = PushButton(FluentIcon.FOLDER, "选择文件夹")
        select_folder_btn.clicked.connect(self._on_select_folder)
        btn_row.addWidget(select_folder_btn)
        
        clear_btn = PushButton(FluentIcon.DELETE, "清空")
        clear_btn.clicked.connect(self._on_clear_files)
        btn_row.addWidget(clear_btn)
        
        btn_row.addStretch()
        file_layout.addLayout(btn_row)
        
        # 进度条
        self.progress_bar = ProgressBar()
        self.progress_bar.setVisible(False)
        file_layout.addWidget(self.progress_bar)
        
        self.progress_label = CaptionLabel("")
        self.progress_label.setVisible(False)
        file_layout.addWidget(self.progress_label)
        
        layout.addWidget(file_card)
        
        # 工具网格
        tools_card = CardWidget()
        tools_layout = QVBoxLayout(tools_card)
        tools_layout.setContentsMargins(20, 16, 20, 16)
        tools_layout.setSpacing(16)
        
        tools_title = SubtitleLabel("处理工具")
        tools_layout.addWidget(tools_title)
        
        # Use responsive FlowLayout
        grid = FlowLayout()
        grid.setSpacing(16)
        
        # 格式转换
        self.convert_tool = ToolCard(
            FluentIcon.SYNC,
            "格式转换",
            "转换音频文件格式\nWAV/FLAC/MP3/OGG"
        )
        self.convert_tool.clicked.connect(self._on_convert)
        grid.addWidget(self.convert_tool)
        
        # 响度标准化
        self.normalize_tool = ToolCard(
            FluentIcon.VOLUME,
            "响度标准化",
            "统一音频响度级别\nEBU R128/流媒体"
        )
        self.normalize_tool.clicked.connect(self._on_normalize)
        grid.addWidget(self.normalize_tool)
        
        # 元数据编辑
        self.metadata_tool = ToolCard(
            FluentIcon.EDIT,
            "元数据编辑",
            "批量编辑音频元数据\n标题/艺术家/专辑"
        )
        self.metadata_tool.clicked.connect(self._on_edit_metadata)
        grid.addWidget(self.metadata_tool)
        
        # 音频分析
        self.analyze_tool = ToolCard(
            FluentIcon.PIE_SINGLE,
            "音频分析",
            "分析音频响度和特征\n（开发中）"
        )
        self.analyze_tool.clicked.connect(self._on_analyze)
        grid.addWidget(self.analyze_tool)
        
        # 批量重命名（链接到命名规则页面）
        self.rename_tool = ToolCard(
            FluentIcon.EDIT,
            "批量重命名",
            "按规则批量重命名\n请使用命名规则页面"
        )
        self.rename_tool.clicked.connect(self._on_rename)
        grid.addWidget(self.rename_tool)
        
        # 导出报告
        self.report_tool = ToolCard(
            FluentIcon.DOCUMENT,
            "导出报告",
            "生成音效库报告\n（开发中）"
        )
        self.report_tool.clicked.connect(self._on_export_report)
        grid.addWidget(self.report_tool)
        
        tools_layout.addLayout(grid)
        layout.addWidget(tools_card)
        
        layout.addStretch()
    
    def _on_select_files(self):
        """选择文件"""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择音频文件",
            "",
            "音频文件 (*.wav *.flac *.mp3 *.ogg *.m4a *.aiff *.opus);;所有文件 (*.*)"
        )
        
        if files:
            self._selected_files = [Path(f) for f in files]
            self._update_file_count()
    
    def _on_select_folder(self):
        """选择文件夹"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择文件夹",
            "",
            QFileDialog.Option.ShowDirsOnly
        )
        
        if folder:
            folder_path = Path(folder)
            audio_extensions = {'.wav', '.flac', '.mp3', '.ogg', '.m4a', '.aiff', '.opus'}
            self._selected_files = [
                f for f in folder_path.rglob('*')
                if f.suffix.lower() in audio_extensions
            ]
            self._update_file_count()
    
    def _on_clear_files(self):
        """清空文件"""
        self._selected_files.clear()
        self._update_file_count()
    
    def _update_file_count(self):
        """更新文件计数"""
        count = len(self._selected_files)
        self.file_count_label.setText(f"已选择 {count} 个文件")
    
    def _check_files_selected(self) -> bool:
        """检查是否选择了文件"""
        if not self._selected_files:
            InfoBar.warning(
                title="提示",
                content="请先选择要处理的文件",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=2000
            )
            return False
        return True
    
    def _on_convert(self):
        """格式转换"""
        if not self._check_files_selected():
            return
        
        # 检查 ffmpeg
        if not self._processor.converter.is_available():
            InfoBar.error(
                title="错误",
                content="未找到 ffmpeg，请先安装 ffmpeg",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000
            )
            return
        
        dialog = FormatConvertDialog(self)
        if dialog.exec():
            options = dialog.get_options()
            
            # 选择输出目录
            output_dir = QFileDialog.getExistingDirectory(
                self, "选择输出目录", ""
            )
            if not output_dir:
                return
            
            options.output_dir = Path(output_dir)
            
            operation = BatchOperation(
                operation_type=BatchOperationType.CONVERT,
                input_files=self._selected_files.copy(),
                conversion_options=options,
            )
            
            self._start_batch(operation)
    
    def _on_normalize(self):
        """响度标准化"""
        if not self._check_files_selected():
            return
        
        # 检查依赖
        if not self._processor.normalizer.is_available():
            InfoBar.error(
                title="错误",
                content="缺少依赖：pyloudnorm 和 soundfile\n请运行: pip install pyloudnorm soundfile",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=4000
            )
            return
        
        dialog = NormalizeDialog(self)
        if dialog.exec():
            options = dialog.get_options()
            
            # 选择输出目录
            output_dir = QFileDialog.getExistingDirectory(
                self, "选择输出目录", ""
            )
            if not output_dir:
                return
            
            options.output_dir = Path(output_dir)
            
            operation = BatchOperation(
                operation_type=BatchOperationType.NORMALIZE,
                input_files=self._selected_files.copy(),
                normalization_options=options,
            )
            
            self._start_batch(operation)
    
    def _on_edit_metadata(self):
        """编辑元数据"""
        if not self._check_files_selected():
            return
        
        dialog = MetadataEditDialog(self)
        if dialog.exec():
            operations = dialog.get_operations()
            
            operation = BatchOperation(
                operation_type=BatchOperationType.EDIT_METADATA,
                input_files=self._selected_files.copy(),
                metadata_operations=operations,
            )
            
            self._start_batch(operation)
    
    def _on_analyze(self):
        """音频分析"""
        InfoBar.info(
            title="开发中",
            content="音频分析功能正在开发中",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=2000
        )
    
    def _on_rename(self):
        """批量重命名"""
        InfoBar.info(
            title="提示",
            content="请使用「命名规则」页面进行批量重命名",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=2000
        )
    
    def _on_export_report(self):
        """导出报告"""
        InfoBar.info(
            title="开发中",
            content="导出报告功能正在开发中",
            parent=self,
            position=InfoBarPosition.TOP,
            duration=2000
        )
    
    def _start_batch(self, operation: BatchOperation):
        """开始批处理"""
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setVisible(True)
        self.progress_label.setText("准备中...")
        
        # 禁用工具卡片
        self._set_tools_enabled(False)
        
        self._worker = BatchWorker(self._processor, operation)
        self._worker.progress.connect(self._on_batch_progress)
        self._worker.finished.connect(self._on_batch_finished)
        self._worker.start()
    
    def _on_batch_progress(self, progress: BatchProgress):
        """批处理进度更新"""
        percent = int(progress.overall_progress * 100)
        self.progress_bar.setValue(percent)
        self.progress_label.setText(
            f"处理中: {progress.current_file} ({progress.processed_files}/{progress.total_files})"
        )
    
    def _on_batch_finished(self, result: BatchResult):
        """批处理完成"""
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self._set_tools_enabled(True)
        
        if result.success:
            InfoBar.success(
                title="完成",
                content=f"成功处理 {result.successful_files} 个文件",
                parent=self,
                position=InfoBarPosition.TOP,
                duration=3000
            )
        else:
            error_msg = f"成功: {result.successful_files}, 失败: {result.failed_files}"
            if result.errors:
                error_msg += f"\n错误: {result.errors[0][:50]}..."
            
            InfoBar.warning(
                title="部分完成",
                content=error_msg,
                parent=self,
                position=InfoBarPosition.TOP,
                duration=4000
            )
    
    def _set_tools_enabled(self, enabled: bool):
        """设置工具卡片启用状态"""
        self.convert_tool.setEnabled(enabled)
        self.normalize_tool.setEnabled(enabled)
        self.metadata_tool.setEnabled(enabled)
        self.analyze_tool.setEnabled(enabled)
        self.rename_tool.setEnabled(enabled)
        self.report_tool.setEnabled(enabled)
