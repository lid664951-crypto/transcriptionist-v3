
import logging
import subprocess
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from qfluentwidgets import (
    TitleLabel, SubtitleLabel, CaptionLabel, BodyLabel,
    PrimaryPushButton, PushButton, TextEdit, LineEdit,
    ElevatedCardWidget, ScrollArea, ComboBox, Slider,
    FluentIcon, InfoBar, InfoBarPosition, ProgressBar,
    FluentIcon, InfoBar, InfoBarPosition, ProgressBar,
    CardWidget
)

from transcriptionist_v3.application.ai_engine.musicgen.prompt_optimizer import MusicGenPromptOptimizer
from transcriptionist_v3.application.ai_engine.musicgen.inference import MusicGenInference
from transcriptionist_v3.ui.utils.workers import MusicGenGenerationWorker, cleanup_thread
from transcriptionist_v3.core.config import AppConfig

import soundfile as sf
import numpy as np
from pathlib import Path
import time

logger = logging.getLogger(__name__)

class AIGenerationPage(QWidget):
    """
    AI 音效生成与续写页面
    Core Features:
    1. 文本生成音效 (Text-to-SFX)
    2. 音频续写 (Coming Soon)
    3. 提示词优化 (Chinese -> AI -> English)
    """
    
    request_play = Signal(str) # Signal to main window to play a file
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiGenerationPage")
        
        # State
        self._inference_engine = None
        self._gen_worker = None
        self._gen_thread = None
        self._last_generated_path = None  # Track last generated file
        
        self._init_ui()
        self._init_logic()
        
    def _init_logic(self):
        """Initialize backend services"""
        self.prompt_optimizer = MusicGenPromptOptimizer()
        
    def _get_inference_engine(self):
        """Lazy init inference engine"""
        if self._inference_engine is None:
            self._inference_engine = MusicGenInference(use_gpu=True)
            # Preload models in background if possible? For now lazy load on first gen
        return self._inference_engine
        
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(20)
        
        # 标题
        title = TitleLabel("AI 音乐工坊 实验室功能")
        layout.addWidget(title)
        
        # 滚动区域
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        content = QWidget()
        content.setStyleSheet(".QWidget { background: transparent; }")
        scroll_layout = QVBoxLayout(content)
        scroll_layout.setContentsMargins(0, 0, 10, 0)
        scroll_layout.setSpacing(20)
        
        # ─────────────────────────────────────────────────────────────
        # 模式选择
        # ─────────────────────────────────────────────────────────────
        mode_card = ElevatedCardWidget()
        mode_layout = QHBoxLayout(mode_card)
        mode_layout.setContentsMargins(20, 16, 20, 16)
        
        mode_label = SubtitleLabel("生成模式")
        self.mode_combo = ComboBox()
        self.mode_combo.addItems(["文本生成音乐 (Text-to-Music)"])
        self.mode_combo.setFixedWidth(250)
        
        mode_layout.addWidget(mode_label)
        mode_layout.addStretch()
        mode_layout.addWidget(self.mode_combo)
        
        scroll_layout.addWidget(mode_card)
        
        # ─────────────────────────────────────────────────────────────
        # 输入区 (左侧) 与 参数区 (右侧)
        # ─────────────────────────────────────────────────────────────
        main_row = QHBoxLayout()
        main_row.setSpacing(20)
        
        # --- 左侧：提示词输入 ---
        input_card = ElevatedCardWidget()
        input_layout = QVBoxLayout(input_card)
        input_layout.setContentsMargins(20, 20, 20, 20)
        input_layout.setSpacing(12)
        
        input_title = SubtitleLabel("描述你的音乐")
        input_layout.addWidget(input_title)
        
        # 用户输入 (中文/英文)
        self.prompt_edit = TextEdit()
        self.prompt_edit.setPlaceholderText("例如：忧郁的钢琴旋律，带有柔和的雨声，慢节奏氛围音乐...\n支持直接输入中文，AI 会自动优化！")
        self.prompt_edit.setMinimumHeight(120)
        input_layout.addWidget(self.prompt_edit)
        
        # 优化按钮行
        opt_row = QHBoxLayout()
        self.optimize_btn = PushButton(FluentIcon.EDIT, "AI 优化提示词", self)
        self.optimize_btn.setToolTip("使用 LLM 将描述转化为专业的英文音乐提示词")
        self.optimize_btn.clicked.connect(self._on_optimize_prompt)
        
        self.optimized_status = CaptionLabel("")
        self.optimized_status.setTextColor(Qt.GlobalColor.gray)
        
        opt_row.addWidget(self.optimize_btn)
        opt_row.addWidget(self.optimized_status)
        opt_row.addStretch()
        input_layout.addLayout(opt_row)
        
        # 优化后结果 (只读/可编辑)
        self.english_prompt = LineEdit()
        self.english_prompt.setPlaceholderText("这里将显示 AI 优化后的英文 Prompt (MusicGen 实际输入)...")
        self.english_prompt.setReadOnly(False) 
        input_layout.addWidget(self.english_prompt)
        
        main_row.addWidget(input_card, 2) # flex=2
        
        # --- 右侧：生成参数 ---
        params_card = ElevatedCardWidget()
        params_layout = QVBoxLayout(params_card)
        params_layout.setContentsMargins(20, 20, 20, 20)
        params_layout.setSpacing(16)
        
        params_title = SubtitleLabel("参数设置")
        params_layout.addWidget(params_title)
        
        # 时长
        self.duration_slider = self._create_slider_row(params_layout, "时长 (秒)", 1, 30, 10)
        
        #由于 MusicGen 本身主要参数较少，这里预留扩展
        # Top-K, Top-P, Temperature 可以在高级设置中
        
        # 生成按钮 (大)
        params_layout.addStretch()
        self.generate_btn = PrimaryPushButton("开始生成")
        self.generate_btn.setMinimumHeight(48)
        self.generate_btn.setStyleSheet("PrimaryPushButton { font-size: 16px; font-weight: bold; }")
        self.generate_btn.clicked.connect(self._on_generate)
        params_layout.addWidget(self.generate_btn)
        
        self.gen_progress = ProgressBar()
        self.gen_progress.setVisible(False)
        params_layout.addWidget(self.gen_progress)
        
        self.gen_status = CaptionLabel("")
        self.gen_status.setVisible(False)
        self.gen_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        params_layout.addWidget(self.gen_status)
        
        main_row.addWidget(params_card, 1) # flex=1
        
        
        scroll_layout.addLayout(main_row)
        
        # ─────────────────────────────────────────────────────────────
        # 生成结果操作区
        # ─────────────────────────────────────────────────────────────
        result_title = SubtitleLabel("生成结果")
        scroll_layout.addWidget(result_title)
        
        result_card = ElevatedCardWidget()
        result_layout = QHBoxLayout(result_card)
        result_layout.setContentsMargins(20, 16, 20, 16)
        result_layout.setSpacing(12)
        
        self.result_label = BodyLabel("等待生成...")
        result_layout.addWidget(self.result_label)
        result_layout.addStretch()
        
        # Export buttons (initially hidden)
        self.play_btn = PushButton(FluentIcon.PLAY, "播放")
        self.play_btn.setVisible(False)
        self.play_btn.clicked.connect(self._on_play_generated)
        result_layout.addWidget(self.play_btn)
         
        self.open_folder_btn = PushButton(FluentIcon.FOLDER, "打开文件夹")
        self.open_folder_btn.setVisible(False)
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        result_layout.addWidget(self.open_folder_btn)
        
        scroll_layout.addWidget(result_card)
        
        scroll_layout.addStretch()
        
        scroll.setWidget(content)
        layout.addWidget(scroll)

    def _create_slider_row(self, layout, text, min_val, max_val, default_val):
        row = QHBoxLayout()
        label = BodyLabel(text)
        val_label = CaptionLabel(str(default_val))
        
        slider = Slider(Qt.Orientation.Horizontal)
        slider.setRange(min_val, max_val)
        slider.setValue(default_val)
        
        slider.valueChanged.connect(lambda v: val_label.setText(str(v)))
        
        row.addWidget(label)
        row.addWidget(slider)
        row.addWidget(val_label)
        
        layout.addLayout(row)
        return slider

    def _on_optimize_prompt(self):
        """优化提示词"""
        user_input = self.prompt_edit.toPlainText().strip()
        if not user_input:
            InfoBar.warning("提示", "请输入描述", parent=self)
            return
            
        self.optimize_btn.setEnabled(False)
        self.optimized_status.setText("优化中...")
        
        # Async invocation for optimization? 
        # Since prompt optimizer uses requests/asyncio internally in sync wrapper, 
        # it might block GUI slightly. Ideally should be in threaded worker.
        # For now, simplistic implementation:
        
        try:
            # TODO: Move to thread if blocking is noticeable
            optimized = self.prompt_optimizer.optimize(user_input)
            self.english_prompt.setText(optimized)
            self.optimized_status.setText("优化完成")
        except Exception as e:
            logger.error(f"Optimization failed: {e}")
            self.optimized_status.setText("优化失败")
            
        self.optimize_btn.setEnabled(True)

    def _on_generate(self):
        """开始生成音频"""
        prompt = self.english_prompt.text().strip()
        if not prompt:
            # Fallback to user input if english prompt is empty
            prompt = self.prompt_edit.toPlainText().strip()
            
        if not prompt:
            InfoBar.warning("提示", "请输入描述或优化后的提示词", parent=self)
            return

        # Prepare UI
        self.generate_btn.setEnabled(False)
        self.gen_progress.setVisible(True)
        self.gen_progress.setValue(0)
        self.gen_status.setVisible(True)
        self.gen_status.setText("准备模型...")

        duration = self.duration_slider.value()

        # Start Worker
        try:
            engine = self._get_inference_engine() # Init engine
            
            self._gen_thread = QThread()
            self._gen_worker = MusicGenGenerationWorker(engine, prompt, duration)
            self._gen_worker.moveToThread(self._gen_thread)
            
            self._gen_thread.started.connect(self._gen_worker.run)
            self._gen_worker.progress.connect(self._on_gen_progress)
            self._gen_worker.finished.connect(self._on_gen_finished)
            self._gen_worker.error.connect(self._on_gen_error)
            
            self._gen_thread.start()
            logger.info(f"Started generation: {prompt}")
            
        except Exception as e:
            self._on_gen_error(str(e))

    def _on_gen_progress(self, current, total, msg):
        self.gen_progress.setValue(current)
        self.gen_status.setText(msg)

    def _on_gen_finished(self, result):
        """生成完成"""
        logger.info("Generation finished")
        cleanup_thread(self._gen_thread, self._gen_worker)
        
        self.generate_btn.setEnabled(True)
        self.gen_progress.setVisible(False)
        self.gen_status.setText("生成完成!")
        
        sample_rate, audio_data = result
        
        # Save to file
        try:
            output_path = self._save_audio(sample_rate, audio_data)
            self._last_generated_path = output_path
            
            # Update result label and show export buttons
            self.result_label.setText(f"✅ 已生成: {output_path.name}")
            self.play_btn.setVisible(True)
            self.open_folder_btn.setVisible(True)
            
            InfoBar.success("成功", f"音频已保存至: {output_path.name}", parent=self)
        except Exception as e:
            logger.error(f"Failed to save audio: {e}")
            InfoBar.error("错误", f"保存失败: {e}", parent=self)

    def _save_audio(self, sample_rate: int, audio_data: np.ndarray) -> Path:
        """保存音频到文件"""
        # Get output directory from config (same as Freesound)
        from transcriptionist_v3.core.config import AppConfig
        configured_path = AppConfig.get("freesound.download_path", "")
        
        if configured_path and configured_path.strip():
            output_dir = Path(configured_path)
        else:
            # Fallback to default - 使用 runtime_config 获取数据目录
            from transcriptionist_v3.runtime.runtime_config import get_data_dir
            data_dir = get_data_dir()
            output_dir = data_dir / "downloads" / "freesound"
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filename with timestamp
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"musicgen_{timestamp}.wav"
        output_path = output_dir / filename
        
        # Save as WAV
        sf.write(str(output_path), audio_data, sample_rate)
        logger.info(f"Saved audio to {output_path}")
        
        return output_path

    def _on_gen_error(self, err_msg):
        logger.error(f"Generation error: {err_msg}")
        cleanup_thread(self._gen_thread, self._gen_worker)
        
        self.generate_btn.setEnabled(True)
        self.gen_progress.setVisible(False)
        self.gen_status.setText("生成失败")
        
        InfoBar.error("错误", f"生成失败: {err_msg}", parent=self)

    def _on_play_generated(self):
        """播放生成的音频"""
        if self._last_generated_path and self._last_generated_path.exists():
            # Emit signal to main window to play
            self.request_play.emit(str(self._last_generated_path.absolute()))
            logger.info(f"Requesting playback for: {self._last_generated_path}")
    
    def _on_add_to_library(self):
        """添加到音效库"""
        if not self._last_generated_path or not self._last_generated_path.exists():
            InfoBar.warning("错误", "没有可用的音频文件", parent=self)
            return
        
        try:
            from transcriptionist_v3.infrastructure.database.connection import get_session
            from transcriptionist_v3.infrastructure.database.models import AudioFile
            from transcriptionist_v3.application.audio_processing.analyzer import AudioAnalyzer
            
            # Analyze audio
            analyzer = AudioAnalyzer()
            metadata = analyzer.analyze(str(self._last_generated_path))
            
            # Add to database
            session = get_session()
            try:
                audio_file = AudioFile(
                    file_path=str(self._last_generated_path),
                    original_filename=self._last_generated_path.name,
                    duration=metadata.duration,
                    sample_rate=metadata.sample_rate,
                    channels=metadata.channels,
                    format=metadata.format,
                    description="AI Generated by MusicGen"
                )
                session.add(audio_file)
                session.commit()
                
                InfoBar.success("成功", "已添加到音效库！", parent=self)
                logger.info(f"Added {self._last_generated_path.name} to library")
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Failed to add to library: {e}")
            InfoBar.error("错误", f"添加失败: {e}", parent=self)
    
    def _on_open_folder(self):
        """打开文件夹"""
        if self._last_generated_path and self._last_generated_path.exists():
            import subprocess
            import sys
            
            folder_path = self._last_generated_path.parent
            if sys.platform == 'win32':
                subprocess.run(['explorer', '/select,', str(self._last_generated_path)])
            else:
                subprocess.run(['open', str(folder_path)])
