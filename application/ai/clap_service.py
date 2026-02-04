
import os
import time
import logging
import json
import numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, Union

# Third-party imports
try:
    import onnxruntime as ort
    import librosa
    from tokenizers import Tokenizer
except ImportError as e:
    logging.getLogger(__name__).warning(f"AI dependencies missing: {e}")

# 官方对齐预处理（与 HuggingFace ClapFeatureExtractor 逐 op 一致，无 PyTorch 依赖）
from transcriptionist_v3.application.ai.clap_preprocess import load_preprocessor_config, CLAPPreprocessor, trim_silence_start

# 多进程 worker 内懒加载的 ONNX 预处理会话（每进程一份，DirectML 加速）
_worker_preprocess_onnx_session: Optional["ort.InferenceSession"] = None
_worker_preprocess_onnx_model_dir: Optional[str] = None
# 性能诊断：每个进程只打一次「首文件」细分耗时，避免刷屏
_timing_logged_pids: set = set()


def _preprocess_onnx_candidates(model_dir: Union[str, Path]) -> List[Path]:
    """返回 preprocess_audio.onnx 的查找顺序：打包时优先用 _MEIPASS 内随包分发的路径。"""
    import sys
    model_dir = Path(model_dir).resolve()
    candidates: List[Path] = []
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        candidates.append(Path(sys._MEIPASS) / "data" / "models" / "onnx_preprocess" / "preprocess_audio.onnx")
    candidates.append(model_dir.parent / "onnx_preprocess" / "preprocess_audio.onnx")
    candidates.append(model_dir / "onnx" / "preprocess_audio.onnx")
    return candidates

# 全局音频预处理函数（用于多进程）
# 必须在模块顶层定义，确保 PyInstaller 打包后子进程可以导入
def _preprocess_audio_static(audio_path: str, model_dir: str) -> Optional[np.ndarray]:
    """
    静态音频预处理函数，用于多进程调用。
    若存在 preprocess_audio.onnx 则用 ONNX Runtime + DirectML 做波形→Mel，否则用 NumPy 官方对齐实现。
    Returns: Mel spectrogram (n_mels, time_steps) or None if failed.
    """
    import sys
    import logging
    import os
    global _worker_preprocess_onnx_session, _worker_preprocess_onnx_model_dir, _timing_logged_pids
    audio_path = str(Path(audio_path).resolve())
    model_dir_norm = str(Path(model_dir).resolve())
    if getattr(sys, 'frozen', False):
        pass
    logger = logging.getLogger(__name__)
    logger.debug(f"[PID {os.getpid()}] Processing: {Path(audio_path).name}")
    do_timing = os.getpid() not in _timing_logged_pids
    try:
        file_ext = Path(audio_path).suffix.lower()
        if file_ext in ['.mp4', '.m4v', '.mov']:
            try:
                import mutagen
                audio_file = mutagen.File(audio_path)
                if audio_file is None:
                    logger.warning(f"Skipping {Path(audio_path).name}: Not a valid audio/video file")
                    return None
                if hasattr(audio_file, 'info') and hasattr(audio_file.info, 'codec'):
                    codec = str(audio_file.info.codec).lower()
                    if 'video' in codec or 'h264' in codec or 'h265' in codec:
                        logger.info(f"Skipping {Path(audio_path).name}: Video file (use audio extraction tool first)")
                        return None
            except Exception as e:
                logger.debug(f"Format check failed for {Path(audio_path).name}, trying to load anyway: {e}")
        config = load_preprocessor_config(model_dir)
        sr = int(config["sampling_rate"])
        t0 = time.perf_counter() if do_timing else None
        # 只加载前 10 秒：CLAP 的感受野大约为 10 秒左右，再多只是浪费解码时间
        # 之前这里使用 20 秒会显著放大 librosa/audioread 的解码耗时（你当前环境里单文件可达 10 秒）
        y, _ = librosa.load(audio_path, sr=sr, duration=10)
        if do_timing:
            t1 = time.perf_counter()
        if y.ndim > 1:
            y = np.mean(y, axis=0)
        y = trim_silence_start(y, sr)
        # LAION-CLAP 官方量化步骤: float32 -> int16 -> float32
        # 这与训练时的 int16_to_float32(float32_to_int16(audio)) 一致
        from transcriptionist_v3.application.ai.clap_preprocess import quantize_audio
        y = quantize_audio(y)
        if do_timing:
            t2 = time.perf_counter()
        preprocessor = CLAPPreprocessor(config=config)
        # 仅当 GPU 加速开启时尝试 ONNX + DirectML 预处理（每进程懒加载一次）
        try:
            from transcriptionist_v3.core.config import AppConfig
            use_gpu = AppConfig.get("ai.gpu_acceleration", True)
        except Exception:
            use_gpu = True
        session = _worker_preprocess_onnx_session if (_worker_preprocess_onnx_model_dir == model_dir_norm and use_gpu) else None
        if session is None and use_gpu:
            try:
                # 打包时优先用 _MEIPASS 内随包分发的 preprocess；否则用 data/models/onnx_preprocess 或模型目录内 onnx/
                onnx_path = None
                for p in _preprocess_onnx_candidates(model_dir_norm):
                    if p.exists():
                        onnx_path = p
                        break
                if onnx_path is not None and onnx_path.exists():
                    providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
                    new_session = ort.InferenceSession(str(onnx_path), providers=providers)
                    _worker_preprocess_onnx_session = new_session
                    _worker_preprocess_onnx_model_dir = model_dir_norm
                    session = new_session
            except Exception as e:
                logger.debug(f"Worker ONNX preprocess not used: {e}")
        if session is not None:
            padded = preprocessor._pad_waveform(y, deterministic_truncate=True)
            waveform_batch = padded.astype(np.float32).reshape(1, -1)
            out = session.run(None, {"waveform": waveform_batch})
            mel_log = out[0][0]
            
            if do_timing:
                t3 = time.perf_counter()
                _timing_logged_pids.add(os.getpid())
                logger.info(
                    "[CLAP 预处理耗时] 单文件(PID=%s) load=%.2fs trim=%.2fs mel(ONNX)=%.2fs",
                    os.getpid(), t1 - t0, t2 - t1, t3 - t2
                )
            return mel_log.astype(np.float32)
        # 无 preprocess_audio.onnx 或 GPU 关闭时回退到 CPU（NumPy）
        mel_log = preprocessor.extract_mel(y, deterministic_truncate=True)
        if do_timing:
            t3 = time.perf_counter()
            _timing_logged_pids.add(os.getpid())
            logger.info(
                "[CLAP 预处理耗时] 单文件(PID=%s) load=%.2fs trim=%.2fs mel(CPU)=%.2fs",
                os.getpid(), t1 - t0, t2 - t1, t3 - t2
            )
        return mel_log
    except FileNotFoundError as e:
        logger.warning(f"File not found: {Path(audio_path).name}")
        return None
    except PermissionError as e:
        logger.warning(f"Permission denied: {Path(audio_path).name}")
        return None
    except Exception as e:
        # 更友好的错误信息
        file_name = Path(audio_path).name
        error_msg = str(e).lower()
        
        if 'codec' in error_msg or 'format' in error_msg:
            logger.warning(f"Unsupported format: {file_name} - {e}")
        elif 'video' in error_msg:
            logger.info(f"Skipping video file: {file_name}")
        else:
            logger.error(f"Audio preprocessing failed for {file_name}: {e}")
        
        return None


logger = logging.getLogger(__name__)

class CLAPInferenceService:
    """
    Service for running CLAP model inference using ONNX Runtime with DirectML.
    音频预处理：与官方 ClapFeatureExtractor 逐 op 一致（clap_preprocess，无 PyTorch/ClapProcessor）。

    单模型 model.onnx（统一双编码器）时：ONNX 图同时包含文本/音频输入，任意一次 run 都必须
    提供全部三个输入（input_ids、attention_mask、input_features），未使用的一路用 dummy 填充：
    - 文本推理（get_text_embedding）：传真实 input_ids/attention_mask + dummy input_features
    - 音频推理（_run_audio_inference）：传真实 input_features + dummy input_ids/attention_mask
    """
    
    SAMPLE_RATE = 48000
    N_FFT = 1024
    HOP_LENGTH = 480
    N_MELS = 64
    MAX_LENGTH_SECONDS = 10
    
    def __init__(self, model_dir: Union[str, Path]):
        self.model_dir = Path(model_dir)
        self.session: Optional[ort.InferenceSession] = None  # 统一模型 session
        self.session_preprocess: Optional[ort.InferenceSession] = None
        self.tokenizer: Optional[Tokenizer] = None
        self._is_ready = False
        self._preprocessor: Optional[CLAPPreprocessor] = None
        self._text_embedding_cache: Dict[str, np.ndarray] = {}
        
    def initialize(self) -> bool:
        """Load model.onnx (统一的双编码器) 与 tokenizer"""
        if self._is_ready:
            return True
        self._text_embedding_cache.clear()
        try:
            # 优先检查统一模型，若不存在则检查分开的模型
            unified_onnx = self.model_dir / "onnx" / "model.onnx"
            audio_onnx = self.model_dir / "onnx" / "audio_model.onnx"
            text_onnx = self.model_dir / "onnx" / "text_model.onnx"
            tokenizer_path = self.model_dir / "tokenizer.json"
            
            # 确定使用哪种模型
            use_unified_model = unified_onnx.exists()
            
            if not use_unified_model:
                if not audio_onnx.exists() or not text_onnx.exists():
                    logger.error(f"CLAP model not found. Please download model.onnx or audio_model.onnx+text_model.onnx")
                    return False
            
            if not tokenizer_path.exists():
                logger.error(f"Tokenizer not found at {tokenizer_path}")
                return False
            
            # 1. Load Tokenizer
            self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
            self.tokenizer.enable_padding(pad_id=1, pad_token="<pad>", length=77)
            self.tokenizer.enable_truncation(max_length=77)
            
            # 2. GPU 配置
            from transcriptionist_v3.core.config import AppConfig
            use_gpu = AppConfig.get("ai.gpu_acceleration", True)
            if use_gpu:
                providers = ['DmlExecutionProvider', 'CPUExecutionProvider']
            else:
                providers = ['CPUExecutionProvider']
            
            # 3. 加载模型
            if use_unified_model:
                logger.info("Loading unified CLAP model (model.onnx)...")
                self.session = ort.InferenceSession(str(unified_onnx), providers=providers)
                # 为兼容旧代码，设置别名
                self.session_audio = self.session
                self.session_text = self.session
            else:
                # 兼容分开的模型（向后兼容）
                logger.info("Loading separate CLAP models (audio_model.onnx + text_model.onnx)...")
                self.session_audio = ort.InferenceSession(str(audio_onnx), providers=providers)
                self.session_text = ort.InferenceSession(str(text_onnx), providers=providers)
                self.session = self.session_audio  # 主 session 指向 audio
            
            # 4. 验证嵌入维度
            try:
                enc = self.tokenizer.encode("test")
                tid = np.array([enc.ids], dtype=np.int64)
                tmask = np.array([enc.attention_mask], dtype=np.int64)
                
                # 统一模型需要同时提供音频和文本输入
                model_inputs = [i.name for i in self.session.get_inputs()]
                feed = {}
                
                if "input_ids" in model_inputs:
                    feed["input_ids"] = tid
                if "attention_mask" in model_inputs:
                    feed["attention_mask"] = tmask
                if "input_features" in model_inputs:
                    # Dummy 音频输入
                    audio_dummy = np.zeros((1, 1, 1001, 64), dtype=np.float32)
                    feed["input_features"] = audio_dummy
                
                outputs = self.session.run(None, feed)
                output_names = [o.name for o in self.session.get_outputs()]
                
                # 获取文本嵌入维度
                if "text_embeds" in output_names:
                    idx = output_names.index("text_embeds")
                    text_dim = int(outputs[idx].shape[-1])
                else:
                    text_dim = int(outputs[0].shape[-1])
                
                # 获取音频嵌入维度
                if "audio_embeds" in output_names:
                    idx = output_names.index("audio_embeds")
                    audio_dim = int(outputs[idx].shape[-1])
                else:
                    audio_dim = text_dim  # 统一模型应该一致
                
                if text_dim != audio_dim:
                    logger.warning(f"Embedding dimension mismatch: text={text_dim}, audio={audio_dim}")
                else:
                    logger.info(f"CLAP: embedding dimension={text_dim}, validation passed")
                    
            except Exception as e:
                logger.warning(f"CLAP embedding validation skipped: {e}")
            
            # 5. 官方对齐预处理
            self._preprocessor = CLAPPreprocessor(model_dir=self.model_dir)
            
            # 6. 可选的 ONNX 预处理加速（打包时优先 _MEIPASS，否则 onnx_preprocess / 模型内 onnx）
            if use_gpu:
                preprocess_onnx = None
                for p in _preprocess_onnx_candidates(self.model_dir):
                    if p.exists():
                        preprocess_onnx = p
                        break
                if preprocess_onnx is not None and preprocess_onnx.exists():
                    try:
                        self.session_preprocess = ort.InferenceSession(str(preprocess_onnx), providers=providers)
                        logger.info("CLAP: audio preprocessing using ONNX + DirectML")
                    except Exception as e:
                        logger.warning(f"CLAP: ONNX preprocess load failed, using NumPy: {e}")
            
            if self.session_preprocess is None:
                logger.info("CLAP: preprocessing uses CPU (NumPy)")
            
            model_name = "unified model.onnx" if use_unified_model else "audio+text models"
            logger.info(f"CLAP ({model_name}) loaded. Device: {self.session.get_providers()[0]}")
            self._is_ready = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize CLAP service: {e}", exc_info=True)
            return False

    def get_text_embedding(self, text: str) -> Optional[np.ndarray]:
        """Generate embedding for text query。
        统一 model.onnx 需同时提供 dummy 音频输入（input_features），否则 ONNX 会报缺输入。
        **CRITICAL: Returns L2-normalized embedding for cosine similarity**
        使用 _text_embedding_cache 避免重复计算，加速 classify_audio。
        """
        if not self._is_ready or not self.tokenizer or not self.session_text:
            return None
        try:
            if text in self._text_embedding_cache:
                return self._text_embedding_cache[text].copy()
        except Exception:
            pass
        try:
            encoded = self.tokenizer.encode(text)
            input_ids = np.array([encoded.ids], dtype=np.int64)
            attention_mask = np.array([encoded.attention_mask], dtype=np.int64)
            model_inputs = [i.name for i in self.session_text.get_inputs()]
            inputs = {}
            if "input_ids" in model_inputs:
                inputs["input_ids"] = input_ids
            if "attention_mask" in model_inputs:
                inputs["attention_mask"] = attention_mask
            # 统一 model.onnx 同时包含文本/音频输入，仅传文本会报缺 input_features
            if "input_features" in model_inputs:
                inputs["input_features"] = np.zeros((1, 1, 1001, 64), dtype=np.float32)

            outputs = self.session_text.run(None, inputs)
            output_names = [o.name for o in self.session_text.get_outputs()]
            if "text_embeds" in output_names:
                idx = output_names.index("text_embeds")
                embedding = outputs[idx][0]
            else:
                embedding = outputs[0][0]
            
            # CRITICAL FIX: L2 normalize text embedding for accurate cosine similarity
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
            self._text_embedding_cache[text] = embedding.copy()
            return embedding

        except Exception as e:
            logger.error(f"Text embedding failed: {e}")
            return None

    def get_audio_embedding(self, audio_path: str) -> Optional[np.ndarray]:
        """Generate embedding for audio file. 使用官方对齐预处理（preprocessor_config.json）。"""
        if not self._is_ready:
            return None
        try:
            mel_log = self._preprocess_audio(audio_path)
            if mel_log is None:
                return None
            # mel_log: (n_mels, time) -> ONNX 期望 (batch, 1, time, mel)
            input_features = mel_log[np.newaxis, np.newaxis, :, :].transpose(0, 1, 3, 2)
            return self._run_audio_inference(input_features.astype(np.float32))
        except Exception as e:
            logger.error(f"Audio embedding failed: {e}")
            return None

    def get_audio_embeddings_batch(
        self,
        audio_paths: list[str],
        batch_size: int = 4,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> dict[str, np.ndarray]:
        """
        Generate embeddings for multiple audio files in batches (OPTIMIZED with chunked multiprocessing)
        
        Args:
            audio_paths: List of audio file paths
            batch_size: Number of files to process in one GPU batch (default: 4)
            progress_callback: Optional (progress_ratio, message_str) for UI progress
                             progress_ratio: 0.0-1.0 representing overall progress
                             message_str: detailed progress message
            
        Returns:
            Dictionary mapping file paths to embeddings
        """
        if not self._is_ready:
            return {}
        
        # 从配置读取设置（官方对齐预处理 preprocessor_config.json）
        from transcriptionist_v3.core.config import AppConfig, get_recommended_indexing_cpu_processes
        
        # 固定使用平衡模式（分块处理 + 渐进检测）
        cpu_processes = AppConfig.get("ai.cpu_processes", None)
        if cpu_processes is None:
            cpu_processes = get_recommended_indexing_cpu_processes()
        
        logger.info(f"Indexing (balanced), CPU processes: {cpu_processes}")
        
        results = {}
        total_files = len(audio_paths)
        
        def _report(progress_ratio: float, msg: str) -> None:
            """统一的进度报告函数，progress_ratio范围0.0-1.0"""
            if progress_callback:
                try:
                    progress_callback(progress_ratio, msg)
                except Exception:
                    pass
        
        return self._process_batch_balanced_mode(audio_paths, batch_size, cpu_processes, total_files, _report)
    
    def _process_batch_performance_mode(
        self,
        audio_paths: list[str],
        batch_size: int,
        cpu_processes: int,
        total_files: int,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> dict[str, np.ndarray]:
        """
        性能优先模式：一次性处理所有文件，无超时保护
        适合高性能机器 + 文件质量可控的场景
        """
        results = {}
        total = len(audio_paths)
        
        # 步骤1：预处理 (0-40%)
        if progress_callback:
            try:
                progress_callback(0.0, "步骤 1/4：正在预处理音频...")
            except Exception:
                pass
        
        if cpu_processes > 1 and len(audio_paths) > 1:
            try:
                from multiprocessing import Pool
                from functools import partial
                
                # CRITICAL: 确保在 PyInstaller 打包后能正确导入
                # 使用完整模块路径导入函数
                from transcriptionist_v3.application.ai.clap_service import _preprocess_audio_static
                
                preprocess_func = partial(_preprocess_audio_static, model_dir=str(self.model_dir))
                
                # 使用 imap 保持路径与结果一一对应（imap_unordered 会打乱顺序）
                t_preprocess_start = time.perf_counter()
                with Pool(processes=cpu_processes) as pool:
                    mel_results = [None] * total
                    processed = 0
                    for idx, result in enumerate(pool.imap(preprocess_func, audio_paths, chunksize=max(1, total // (cpu_processes * 4)))):
                        mel_results[idx] = result
                        processed += 1
                        # 每100个文件或每10%更新一次进度
                        if processed % max(1, total // 10) == 0 or processed == total:
                            progress = 0.0 + (processed / total) * 0.4  # 0-40%
                            if progress_callback:
                                try:
                                    progress_callback(progress, f"步骤 1/4：预处理音频 {processed}/{total}")
                                except Exception:
                                    pass
                
                # 过滤失败的结果
                valid_mels = []
                valid_paths = []
                for path, mel_log in zip(audio_paths, mel_results):
                    if mel_log is not None:
                        valid_mels.append(mel_log)
                        valid_paths.append(path)
                
                t_preprocess_end = time.perf_counter()
                if not valid_mels:
                    return {}
                
                # 步骤2：批量 GPU 推理 (40-80%)
                total_batches = (len(valid_mels) + batch_size - 1) // batch_size
                t_inference_start = time.perf_counter()
                for batch_idx, i in enumerate(range(0, len(valid_mels), batch_size)):
                    batch_mels = valid_mels[i:i + batch_size]
                    batch_paths = valid_paths[i:i + batch_size]
                    
                    batch_features = np.stack([mel[np.newaxis, :, :] for mel in batch_mels], axis=0)
                    batch_features = batch_features.transpose(0, 1, 3, 2)
                    
                    embeddings = self._run_audio_inference(batch_features)
                    
                    if embeddings is not None:
                        if embeddings.ndim == 1:
                            results[batch_paths[0]] = embeddings
                        else:
                            for path, emb in zip(batch_paths, embeddings):
                                results[path] = emb
                    
                    # 更新GPU推理进度
                    progress = 0.4 + ((batch_idx + 1) / total_batches) * 0.4  # 40-80%
                    if progress_callback:
                        try:
                            progress_callback(progress, f"步骤 2/4：GPU推理 batch {batch_idx + 1}/{total_batches}")
                        except Exception:
                            pass
                
                t_inference_end = time.perf_counter()
                logger.info(
                    "[CLAP 阶段耗时] 预处理=%.1fs, GPU推理=%.1fs, 有效文件=%d | 若预处理远大于推理则瓶颈在 CPU/IO(librosa)",
                    t_preprocess_end - t_preprocess_start, t_inference_end - t_inference_start, len(valid_mels)
                )
                # 步骤3：归一化已在_run_audio_inference中完成 (80-90%)
                if progress_callback:
                    try:
                        progress_callback(0.9, "步骤 3/4：归一化完成")
                    except Exception:
                        pass
                
                # 步骤4：保存索引在外部完成 (90-100%)
                if progress_callback:
                    try:
                        progress_callback(1.0, "步骤 4/4：索引建立完成")
                    except Exception:
                        pass
                return results
                
            except Exception as e:
                logger.error(f"Performance mode failed: {e}, falling back to single process")
                # Fall through to single process mode
        
        # 单进程回退
        return self._process_single_thread(audio_paths, batch_size)
    
    def _process_batch_balanced_mode(
        self,
        audio_paths: list[str],
        batch_size: int,
        cpu_processes: int,
        total_files: int,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> dict[str, np.ndarray]:
        """
        平衡模式：分块处理 + 渐进检测
        每块独立处理，超时只影响当前块
        """
        from transcriptionist_v3.core.config import AppConfig

        results = {}
        total_files = len(audio_paths)
        
        # 块大小与规则：从配置读取，严格内存上限避免百万级 OOM（P0 优化）
        CHUNK_SIZE_MIN, CHUNK_SIZE_MAX = 100, 3000  # 上限 3000，与 get_recommended_indexing_chunk_size 一致，避免单块占用过多内存

        # 可选：内存限制 MB，用于进一步约束单块文件数（估算：每文件 mel 约 64*1001*4 字节）
        memory_limit_mb = AppConfig.get("ai.indexing_memory_limit_mb", None)
        if memory_limit_mb is not None and isinstance(memory_limit_mb, (int, float)) and memory_limit_mb > 0:
            bytes_per_mel = 64 * 1001 * 4  # 单条 mel 约 256KB
            cap_by_memory = int((memory_limit_mb * 1024 * 1024) // bytes_per_mel)
            effective_max = min(CHUNK_SIZE_MAX, max(CHUNK_SIZE_MIN, cap_by_memory))
        else:
            effective_max = CHUNK_SIZE_MAX

        raw_chunk = AppConfig.get("ai.indexing_chunk_size", None)
        # 少于 500 文件时不拆块，固定硬编码（不再暴露 UI）
        small_threshold = 500

        if raw_chunk is not None and raw_chunk != "":
            try:
                chunk_size = max(CHUNK_SIZE_MIN, min(effective_max, int(raw_chunk)))
            except (TypeError, ValueError):
                chunk_size = None
        else:
            chunk_size = None
        if chunk_size is None:
            from transcriptionist_v3.core.config import get_recommended_indexing_chunk_size
            chunk_size = get_recommended_indexing_chunk_size()
            chunk_size = max(CHUNK_SIZE_MIN, min(effective_max, chunk_size))
        
        if total_files < small_threshold:
            chunk_size = total_files  # 小批量不拆块，一次处理
        logger.info(f"[Balanced Mode] Processing {total_files} files in chunks of {chunk_size} (small_threshold={small_threshold})")
        
        # 分块处理
        for chunk_idx in range(0, total_files, chunk_size):
            chunk_paths = audio_paths[chunk_idx:chunk_idx + chunk_size]
            chunk_num = chunk_idx // chunk_size + 1
            total_chunks = (total_files + chunk_size - 1) // chunk_size
            
            logger.info(f"[Chunk {chunk_num}/{total_chunks}] Processing {len(chunk_paths)} files...")
            
            # 处理当前块，传递进度回调
            def chunk_progress_callback(chunk_progress: float, msg: str):
                """将块内进度转换为全局进度"""
                # 计算当前块在总进度中的位置
                chunk_start = chunk_idx / total_files
                chunk_weight = len(chunk_paths) / total_files
                global_progress = chunk_start + chunk_progress * chunk_weight
                
                if progress_callback:
                    try:
                        progress_callback(global_progress, msg)
                    except Exception:
                        pass
            
            chunk_results = self._process_chunk(chunk_paths, batch_size, cpu_processes, chunk_num, chunk_progress_callback)
            results.update(chunk_results)
            
            logger.info(f"[Chunk {chunk_num}/{total_chunks}] Completed, got {len(chunk_results)} embeddings")
        
        return results
    
    def _process_chunk(self, chunk_paths: list[str], batch_size: int, cpu_processes: int, chunk_num: int, progress_callback: Optional[Callable[[float, str], None]] = None) -> dict[str, np.ndarray]:
        """
        处理单个块，带超时保护，支持流式进度报告
        """
        results = {}
        total = len(chunk_paths)
        
        # 步骤1：预处理 (0-40%)
        if progress_callback:
            try:
                progress_callback(0.0, f"块 {chunk_num}：步骤 1/4 预处理音频...")
            except Exception:
                pass
        
        # 单文件超时：某个文件解码卡住（如损坏/异常编码）时跳过，避免整块卡在 21%
        per_file_timeout = 90  # 秒，单文件最长等待时间
        
        if cpu_processes > 1 and len(chunk_paths) > 1:
            try:
                from multiprocessing import Pool, TimeoutError as MPTimeoutError
                from functools import partial
                
                # CRITICAL: 确保在 PyInstaller 打包后能正确导入
                from transcriptionist_v3.application.ai.clap_service import _preprocess_audio_static
                
                preprocess_func = partial(_preprocess_audio_static, model_dir=str(self.model_dir))
                
                valid_mels = []
                valid_paths = []
                
                t_preprocess_start = time.perf_counter()
                with Pool(processes=cpu_processes) as pool:
                    # 用 apply_async + get(timeout) 实现单文件超时，避免一个坏文件卡住整块
                    pending = [(path, pool.apply_async(preprocess_func, (path,))) for path in chunk_paths]
                    processed = 0
                    for path, ar in pending:
                        try:
                            mel_log = ar.get(timeout=per_file_timeout)
                            if mel_log is not None:
                                valid_mels.append(mel_log)
                                valid_paths.append(path)
                        except MPTimeoutError:
                            logger.warning(f"[Chunk {chunk_num}] Preprocessing timeout ({per_file_timeout}s), skipping: {Path(path).name}")
                        except Exception as e:
                            logger.debug(f"Preprocessing failed for {Path(path).name}: {e}")
                        processed += 1
                        # 每约 10% 或每 100 个更新一次进度
                        if processed % max(1, min(100, total // 10)) == 0 or processed == total:
                            progress = 0.0 + (processed / total) * 0.4  # 0-40%
                            if progress_callback:
                                try:
                                    progress_callback(progress, f"块 {chunk_num}：预处理 {processed}/{total}")
                                except Exception:
                                    pass
                
                t_preprocess_end = time.perf_counter()
                # 失败/超时的已跳过，valid_mels/valid_paths 已按路径一一对应
                
                if not valid_mels:
                    return {}
                
                # 步骤2：批量 GPU 推理 (40-80%)
                total_batches = (len(valid_mels) + batch_size - 1) // batch_size
                t_inference_start = time.perf_counter()
                for batch_idx, i in enumerate(range(0, len(valid_mels), batch_size)):
                    batch_mels = valid_mels[i:i + batch_size]
                    batch_paths = valid_paths[i:i + batch_size]
                    
                    batch_features = np.stack([mel[np.newaxis, :, :] for mel in batch_mels], axis=0)
                    batch_features = batch_features.transpose(0, 1, 3, 2)
                    
                    embeddings = self._run_audio_inference(batch_features)
                    
                    if embeddings is not None:
                        if embeddings.ndim == 1:
                            results[batch_paths[0]] = embeddings
                        else:
                            for path, emb in zip(batch_paths, embeddings):
                                results[path] = emb
                    
                    # 更新GPU推理进度
                    progress = 0.4 + ((batch_idx + 1) / total_batches) * 0.4  # 40-80%
                    if progress_callback:
                        try:
                            progress_callback(progress, f"块 {chunk_num}：GPU推理 batch {batch_idx + 1}/{total_batches}")
                        except Exception:
                            pass
                
                t_inference_end = time.perf_counter()
                logger.info(
                    "[CLAP 阶段耗时] 块%d 预处理=%.1fs, GPU推理=%.1fs, 有效文件=%d",
                    chunk_num, t_preprocess_end - t_preprocess_start, t_inference_end - t_inference_start, len(valid_mels)
                )
                # 步骤3：归一化已在_run_audio_inference中完成 (80-90%)
                if progress_callback:
                    try:
                        progress_callback(0.9, f"块 {chunk_num}：步骤 3/4 归一化完成")
                    except Exception:
                        pass
                
                return results
                
            except Exception as e:
                logger.error(f"[Chunk {chunk_num}] Processing failed: {e}")
                return {}
        
        # 单进程模式
        return self._process_single_thread(chunk_paths, batch_size)
    
    def _process_single_thread(self, audio_paths: list[str], batch_size: int) -> dict[str, np.ndarray]:
        """
        单进程模式处理（回退方案）
        """
        results = {}
        
        for i in range(0, len(audio_paths), batch_size):
            batch_paths = audio_paths[i:i + batch_size]
            
            try:
                mel_features = []
                valid_paths = []
                
                for path in batch_paths:
                    mel_log = self._preprocess_audio(path)
                    if mel_log is not None:
                        mel_features.append(mel_log)
                        valid_paths.append(path)
                
                if not mel_features:
                    continue
                
                batch_features = np.stack([mel[np.newaxis, :, :] for mel in mel_features], axis=0)
                batch_features = batch_features.transpose(0, 1, 3, 2)
                
                embeddings = self._run_audio_inference(batch_features)
                
                if embeddings is not None:
                    if embeddings.ndim == 1:
                        results[valid_paths[0]] = embeddings
                    else:
                        for path, emb in zip(valid_paths, embeddings):
                            results[path] = emb
                
            except Exception as e:
                logger.error(f"Batch embedding failed: {e}")
                for path in batch_paths:
                    try:
                        emb = self.get_audio_embedding(path)
                        if emb is not None:
                            results[path] = emb
                    except:
                        pass
        
        return results

    def _preprocess_audio(self, audio_path: str) -> Optional[np.ndarray]:
        """
        单文件预处理：若已加载 preprocess_audio.onnx 则用 ONNX + DirectML，否则与官方 ClapFeatureExtractor 逐 op 一致（NumPy）。
        Returns: Mel spectrogram (n_mels, time_steps) or None if failed.
        """
        try:
            file_ext = Path(audio_path).suffix.lower()
            if file_ext in ['.mp4', '.m4v', '.mov']:
                try:
                    import mutagen
                    audio_file = mutagen.File(audio_path)
                    if audio_file is None:
                        logger.warning(f"Skipping {Path(audio_path).name}: Not a valid audio/video file")
                        return None
                    if hasattr(audio_file, 'info') and hasattr(audio_file.info, 'codec'):
                        codec = str(audio_file.info.codec).lower()
                        if 'video' in codec or 'h264' in codec or 'h265' in codec:
                            logger.info(f"Skipping {Path(audio_path).name}: Video file (use audio extraction tool first)")
                            return None
                except Exception as e:
                    logger.debug(f"Format check failed for {Path(audio_path).name}, trying to load anyway: {e}")
            sr = self._preprocessor.sampling_rate
            # 与多进程版本保持一致：仅加载前 10 秒，避免对长文件做不必要的全长解码
            y, _ = librosa.load(audio_path, sr=sr, duration=10)
            if y.ndim > 1:
                y = np.mean(y, axis=0)
            y = trim_silence_start(y, sr)
            # LAION-CLAP 官方量化步骤
            from transcriptionist_v3.application.ai.clap_preprocess import quantize_audio
            y = quantize_audio(y)
            if self.session_preprocess is not None:
                padded = self._preprocessor._pad_waveform(y, deterministic_truncate=True)
                waveform_batch = padded.astype(np.float32).reshape(1, -1)
                out = self.session_preprocess.run(None, {"waveform": waveform_batch})
                return out[0][0].astype(np.float32)
            return self._preprocessor.extract_mel(y, deterministic_truncate=True)
        except FileNotFoundError as e:
            logger.warning(f"File not found: {Path(audio_path).name}")
            return None
        except PermissionError as e:
            logger.warning(f"Permission denied: {Path(audio_path).name}")
            return None
        except Exception as e:
            # 更友好的错误信息
            file_name = Path(audio_path).name
            error_msg = str(e).lower()
            
            if 'codec' in error_msg or 'format' in error_msg:
                logger.warning(f"Unsupported format: {file_name} - {e}")
            elif 'video' in error_msg:
                logger.info(f"Skipping video file: {file_name}")
            else:
                logger.error(f"Audio preprocessing failed for {file_name}: {e}")
            
            return None

    def _run_audio_inference(self, input_features: np.ndarray) -> Optional[np.ndarray]:
        """
        Run audio_model.onnx on preprocessed audio features。
        若为统一 model.onnx（双编码器），需同时提供 dummy 文本输入（input_ids/attention_mask），否则 ONNX 会报缺输入。
        
        Args:
            input_features: Shape (batch_size, 1, time_steps, n_mels) or (1, 1, time_steps, n_mels)
            
        Returns:
            Embeddings of shape (batch_size, embed_dim) or (embed_dim,) for single input
            **CRITICAL: Embeddings are L2-normalized for cosine similarity**
        """
        if not self.session_audio:
            return None
        try:
            model_inputs = [i.name for i in self.session_audio.get_inputs()]
            batch_size = int(input_features.shape[0])
            feed_dict = {}
            if "input_features" in model_inputs:
                feed_dict["input_features"] = input_features.astype(np.float32)
            else:
                for name in model_inputs:
                    if "feature" in name.lower() or "audio" in name.lower():
                        feed_dict[name] = input_features.astype(np.float32)
                        break
                if not feed_dict:
                    feed_dict[model_inputs[0]] = input_features.astype(np.float32)
            # 统一 model.onnx 同时包含文本/音频输入，仅传 input_features 会报缺 input_ids/attention_mask
            if "input_ids" in model_inputs:
                # pad_id=1, length=77 与 tokenizer 配置一致
                feed_dict["input_ids"] = np.full((batch_size, 77), 1, dtype=np.int64)
            if "attention_mask" in model_inputs:
                feed_dict["attention_mask"] = np.zeros((batch_size, 77), dtype=np.int64)

            outputs = self.session_audio.run(None, feed_dict)
            output_names = [o.name for o in self.session_audio.get_outputs()]
            if "audio_embeds" in output_names:
                idx = output_names.index("audio_embeds")
                embeddings = outputs[idx]
            else:
                embeddings = outputs[0]
            
            # CRITICAL FIX: L2 normalize embeddings for accurate cosine similarity
            # CLAP模型输出的embedding需要归一化才能正确计算相似度
            if embeddings.ndim == 1:
                norm = np.linalg.norm(embeddings)
                if norm > 0:
                    embeddings = embeddings / norm
            else:
                norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
                norms = np.where(norms > 0, norms, 1.0)  # 避免除零
                embeddings = embeddings / norms
            
            if embeddings.shape[0] == 1:
                return embeddings[0]
            return embeddings
            
        except Exception as e:
            logger.error(f"Audio inference failed: {e}")
            return None

    def classify_audio(self, audio_embedding: np.ndarray, candidate_labels: list[str], top_k: int = 3) -> list[tuple[str, float]]:
        """
        Perform zero-shot classification (tagging) for a given audio embedding.
        P0 优化：标签较多时使用矩阵化相似度计算 + 文本向量缓存，避免十万级标签下数小时耗时。
        
        Args:
            audio_embedding: The audio embedding vector (L2-normalized).
            candidate_labels: List of text labels to compare against.
            top_k: Number of top matches to return.
            
        Returns:
            List of (label, score) tuples, sorted by score descending.
        """
        if audio_embedding is None or not candidate_labels:
            return []

        # 矩阵路径：候选数较多时一次性取所有文本向量，做一次矩阵乘法
        use_matrix = len(candidate_labels) >= 20
        if use_matrix:
            try:
                emb_list = []
                valid_labels = []
                for label in candidate_labels:
                    text_embed = self.get_text_embedding(label)
                    if text_embed is not None:
                        emb_list.append(text_embed)
                        valid_labels.append(label)
                if not emb_list:
                    return []
                embedding_matrix = np.stack(emb_list, axis=0)  # (N, dim)
                # 余弦相似度：向量已归一化，即 dot(audio, text) = cos_sim
                similarities = np.dot(embedding_matrix, audio_embedding)
                top_indices = np.argpartition(-similarities, min(top_k, len(valid_labels) - 1))[:top_k]
                top_indices = top_indices[np.argsort(-similarities[top_indices])]
                return [(valid_labels[i], float(similarities[i])) for i in top_indices]
            except Exception as e:
                logger.debug(f"Matrix classify_audio fallback: {e}")
                use_matrix = False

        if not use_matrix:
            scores = []
            for label in candidate_labels:
                text_embed = self.get_text_embedding(label)
                if text_embed is None:
                    continue
                norm_audio = np.linalg.norm(audio_embedding)
                norm_text = np.linalg.norm(text_embed)
                if norm_audio == 0 or norm_text == 0:
                    sim = 0.0
                else:
                    sim = np.dot(audio_embedding, text_embed) / (norm_audio * norm_text)
                scores.append((label, float(sim)))
            scores.sort(key=lambda x: x[1], reverse=True)
            return scores[:top_k]

        return []
