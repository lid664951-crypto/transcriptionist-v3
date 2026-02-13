"""
HY-MT1.5 ONNX Translation Service

使用 ONNX Runtime 运行 HY-MT1.5 专用翻译模型。
支持 GPU (CUDA/DirectML) 和 CPU 自动切换。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional

import numpy as np

from ..base import (
    AIResult,
    AIResultStatus,
    AIServiceConfig,
    ProgressCallback,
    TranslationResult,
    TranslationService,
)

logger = logging.getLogger(__name__)

try:
    import onnxruntime as ort
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False
    logger.warning("onnxruntime not available, HY-MT1.5 ONNX service will not work")

try:
    from tokenizers import Tokenizer
    TOKENIZER_AVAILABLE = True
except ImportError:
    TOKENIZER_AVAILABLE = False
    logger.warning("tokenizers library not available, HY-MT1.5 ONNX service will not work")


class HyMT15OnnxService(TranslationService):
    """
    HY-MT1.5 ONNX 翻译服务
    
    使用 ONNX Runtime 运行本地 ONNX 模型进行翻译。
    支持 GPU (CUDA/DirectML) 和 CPU 自动切换。
    """
    
    SERVICE_ID = "hy_mt15_onnx"
    SERVICE_NAME = "HY-MT1.5 ONNX"
    SERVICE_DESC = "腾讯开源专用翻译模型 (ONNX Runtime)"
    
    def __init__(self, config: AIServiceConfig):
        super().__init__(config)
        self._session: Optional[ort.InferenceSession] = None
        self._tokenizer = None
        self._model_path: Optional[Path] = None
        self._providers = []
        
    def _get_model_path(self) -> Optional[Path]:
        """获取模型路径"""
        from transcriptionist_v3.runtime.runtime_config import get_data_dir
        
        model_dir = get_data_dir() / "models" / "hy-mt1.5-onnx"
        
        # 检查必需文件
        onnx_file = model_dir / "model_fp16.onnx"
        if not onnx_file.exists():
            logger.error(f"ONNX model file not found: {onnx_file}")
            return None
        
        return onnx_file
    
    def _load_tokenizer(self):
        """加载 tokenizer"""
        if not TOKENIZER_AVAILABLE:
            raise RuntimeError("tokenizers library not available. Please install: pip install tokenizers")
        
        from transcriptionist_v3.runtime.runtime_config import get_data_dir
        
        model_dir = get_data_dir() / "models" / "hy-mt1.5-onnx"
        tokenizer_file = model_dir / "tokenizer.json"
        
        if not tokenizer_file.exists():
            raise FileNotFoundError(f"Tokenizer file not found: {tokenizer_file}")
        
        try:
            # 使用 tokenizers 库加载（与 MusicGen 和 CLAP 相同的方式）
            self._tokenizer = Tokenizer.from_file(str(tokenizer_file))
            logger.info(f"Tokenizer loaded from {tokenizer_file}")
        except Exception as e:
            logger.error(f"Failed to load tokenizer: {e}")
            raise
    
    def _get_providers(self) -> List[str]:
        """获取可用的执行提供者（按优先级排序）"""
        if not ONNX_AVAILABLE:
            return []
        
        providers = []
        available = ort.get_available_providers()
        
        # 优先级：CUDA > DirectML > CPU
        if "CUDAExecutionProvider" in available:
            providers.append("CUDAExecutionProvider")
        elif "DmlExecutionProvider" in available:
            providers.append("DmlExecutionProvider")
        
        # CPU 总是可用
        providers.append("CPUExecutionProvider")
        
        return providers
    
    async def initialize(self) -> None:
        """初始化 ONNX 模型"""
        if not ONNX_AVAILABLE:
            raise RuntimeError("onnxruntime not available. Please install onnxruntime-gpu or onnxruntime")
        
        model_path = self._get_model_path()
        if model_path is None:
            raise FileNotFoundError("HY-MT1.5 ONNX model not found")
        
        self._model_path = model_path
        self._providers = self._get_providers()
        
        # 创建推理会话
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        
        try:
            self._session = ort.InferenceSession(
                str(model_path),
                sess_options=sess_options,
                providers=self._providers
            )
            
            logger.info(f"HY-MT1.5 ONNX model loaded with providers: {self._providers}")
            
            # 加载 tokenizer
            self._load_tokenizer()
            
        except Exception as e:
            logger.error(f"Failed to initialize ONNX model: {e}")
            raise
    
    async def test_connection(self) -> AIResult[bool]:
        """测试模型是否可用"""
        try:
            if self._session is None:
                await self.initialize()
            
            # 简单的测试推理
            test_input = ["Hello"]
            result = await self.translate_batch(test_input)
            
            if result.success:
                return AIResult(status=AIResultStatus.SUCCESS, data=True)
            else:
                return AIResult(
                    status=AIResultStatus.ERROR,
                    data=False,
                    error=result.error
                )
        except Exception as e:
            return AIResult(
                status=AIResultStatus.ERROR,
                data=False,
                error=str(e)
            )
    
    async def translate(
        self,
        text: str,
        source_lang: str = "en",
        target_lang: str = "zh",
    ) -> AIResult[TranslationResult]:
        """翻译单个文本"""
        result = await self.translate_batch([text], source_lang, target_lang)
        
        if result.success and result.data:
            return AIResult(
                status=result.status,
                data=result.data[0] if result.data else None,
                error=result.error
            )
        else:
            return AIResult(
                status=result.status,
                error=result.error
            )
    
    def _encode_text(self, text: str, max_length: int = 512) -> tuple[np.ndarray, np.ndarray]:
        """
        使用 tokenizer 编码文本
        
        Returns:
            (input_ids, attention_mask): 编码后的 token IDs 和注意力掩码
        """
        if not self._tokenizer:
            raise RuntimeError("Tokenizer not loaded")
        
        # 编码文本（参考 MusicGen 和 CLAP 的实现）
        encoding = self._tokenizer.encode(text)
        token_ids = encoding.ids
        
        # 截断或填充到指定长度
        if len(token_ids) > max_length:
            token_ids = token_ids[:max_length]
        else:
            # 填充到 max_length（使用 pad_token_id，通常是 0）
            pad_token_id = 0
            token_ids = token_ids + [pad_token_id] * (max_length - len(token_ids))
        
        # 创建 attention_mask（1 表示真实 token，0 表示 padding）
        attention_mask = [1] * len(encoding.ids)
        if len(attention_mask) > max_length:
            attention_mask = attention_mask[:max_length]
        else:
            attention_mask = attention_mask + [0] * (max_length - len(attention_mask))
        
        # 转换为 numpy 数组，形状为 (1, sequence_length)
        input_ids = np.array([token_ids], dtype=np.int64)
        attention_mask_array = np.array([attention_mask], dtype=np.int64)
        
        return input_ids, attention_mask_array
    
    def _decode_tokens(self, token_ids: np.ndarray) -> str:
        """
        使用 tokenizer 解码 token IDs 为文本，并进行清洗以确保结果可用于文件名
        """
        if not self._tokenizer:
            raise RuntimeError("Tokenizer not loaded")
        
        # 将 numpy 数组转换为列表
        if isinstance(token_ids, np.ndarray):
            token_ids = token_ids.tolist()
        
        # 如果是批量输出，取第一个
        if isinstance(token_ids[0], list):
            token_ids = token_ids[0]
        
        # 解码（移除特殊 token，如 padding）
        decoded = self._tokenizer.decode(token_ids, skip_special_tokens=True)
        if not decoded:
            return ""
        
        # 移除所有控制字符（换行、回车、制表符等）
        decoded = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', decoded)
        
        # 只保留首行，避免换行符后长串垃圾内容
        decoded = decoded.splitlines()[0].strip()
        
        # 清理 Windows 文件名非法字符，避免重命名时报 WinError 87
        # 包括：< > : " / \ | ? * 以及控制字符
        decoded = re.sub(r'[<>:"/\\\\|?*\x00-\x1f\x7f-\x9f]', "", decoded)
        
        # 移除前后空白和点号（Windows 文件名不能以点开头或结尾）
        decoded = decoded.strip('. \t\n\r')
        
        # 将连续感叹号压缩成一个（全角），防止出现超长 "!!!!..."
        decoded = re.sub(r"[!！]{2,}", "！", decoded)
        
        # 移除连续空格，压缩为单个空格
        decoded = re.sub(r'\s+', ' ', decoded)
        
        # 安全长度限制，避免生成过长文件名片段
        max_len = 32
        if len(decoded) > max_len:
            decoded = decoded[:max_len].rstrip()
        
        # 最终清理：确保不是空字符串或只有空白
        decoded = decoded.strip()
        
        return decoded if decoded else ""
    
    async def translate_batch(
        self,
        texts: List[str],
        source_lang: str = "en",
        target_lang: str = "zh",
        progress_callback: Optional[ProgressCallback] = None,
    ) -> AIResult[List[TranslationResult]]:
        """
        批量翻译
        
        实现步骤：
        1. 使用 tokenizer 编码输入文本为 token IDs
        2. 准备模型输入（input_ids, attention_mask 等）
        3. 调用 ONNX 模型进行推理
        4. 解码输出 token IDs 为文本
        """
        if not texts:
            return AIResult(status=AIResultStatus.SUCCESS, data=[])
        
        try:
            if self._session is None:
                await self.initialize()
            
            if not self._tokenizer:
                raise RuntimeError("Tokenizer not loaded")
            
            # 获取模型输入输出信息
            model_inputs = {inp.name: inp for inp in self._session.get_inputs()}
            model_outputs = [out.name for out in self._session.get_outputs()]
            
            logger.debug(f"Model inputs: {list(model_inputs.keys())}")
            logger.debug(f"Model outputs: {model_outputs}")
            
            results: List[TranslationResult] = []
            
            # 批量处理（根据用户设置的批次大小）
            from transcriptionist_v3.core.config import AppConfig, get_recommended_translate_chunk_size
            batch_size = AppConfig.get("ai.translate_chunk_size", None)
            if batch_size is None:
                batch_size = get_recommended_translate_chunk_size(
                    "local",
                    AppConfig.get("ai.translate_network_profile", "normal"),
                )
            else:
                try:
                    batch_size = int(batch_size)
                except (TypeError, ValueError):
                    batch_size = get_recommended_translate_chunk_size(
                        "local",
                        AppConfig.get("ai.translate_network_profile", "normal"),
                    )
            # 为本地 ONNX 模型设置一个更保守的安全区间，避免显存/内存压力过大
            if batch_size < 1:
                batch_size = 1
            if batch_size > 80:
                logger.info(f"HY-MT1.5 ONNX: clamp batch_size from {batch_size} to 80 for stability")
                batch_size = 80
            
            for batch_start in range(0, len(texts), batch_size):
                batch_texts = texts[batch_start:batch_start + batch_size]
                
                if progress_callback:
                    progress_callback(batch_start, len(texts), f"翻译批次 {batch_start // batch_size + 1}...")
                
                batch_results: List[TranslationResult] = []
                
                # 目前以“逐条”方式推理，先保证稳定性
                for text in batch_texts:
                    try:
                        # 1. 按官方模板构建 prompt，并编码为 token id 序列
                        prompt_text = self._build_prompt(text, source_lang, target_lang)
                        if not self._tokenizer:
                            raise RuntimeError("Tokenizer not loaded")
                        encoding = self._tokenizer.encode(prompt_text)
                        curr_ids: List[int] = list(encoding.ids)
                        prompt_len = len(curr_ids)
                        
                        # 为文件名翻译设置较小的生成长度（文件名通常很短，15个token足够）
                        max_new_tokens = 15
                        
                        # 动态调整 max_length：prompt + 生成部分，但不超过128
                        # 这样可以减少每一步的计算量
                        dynamic_max_length = min(128, prompt_len + max_new_tokens + 10)
                        
                        # 尝试获取 EOS token ID（如果 tokenizer 支持）
                        eos_token_id = None
                        try:
                            # 某些 tokenizer 可能有 eos_token_id 属性
                            if hasattr(self._tokenizer, 'eos_token_id') and self._tokenizer.eos_token_id is not None:
                                eos_token_id = self._tokenizer.eos_token_id
                        except:
                            pass
                        
                        # 2. 优化的贪心自回归生成循环
                        for step in range(max_new_tokens):
                            inputs, seq_len = self._build_step_inputs(curr_ids, model_inputs, max_length=dynamic_max_length)
                            outputs = self._session.run(None, inputs)
                            
                            if not outputs:
                                logger.warning("HY-MT1.5 ONNX model returned no outputs during generation")
                                break
                            
                            logits = outputs[0]
                            if not isinstance(logits, np.ndarray) or logits.ndim != 3:
                                logger.warning(f"Unexpected logits shape from HY-MT1.5 ONNX: {getattr(logits, 'shape', None)}")
                                break
                            
                            # 取当前序列最后一个位置的 logits 做贪心选取
                            last_pos = min(seq_len - 1, logits.shape[1] - 1)
                            next_token_id = int(logits[0, last_pos].argmax(axis=-1))
                            curr_ids.append(next_token_id)
                            
                            # 优化的停止条件：
                            # 1. EOS token
                            if eos_token_id is not None and next_token_id == eos_token_id:
                                break
                            # 2. Padding token（通常表示结束）
                            if next_token_id == 0:
                                break
                            # 3. 提前解码检查：如果已经生成了足够的内容（检测到句号、换行等），提前停止
                            if step >= 5:  # 至少生成5个token后再检查
                                try:
                                    temp_decoded = self._tokenizer.decode(curr_ids[prompt_len:], skip_special_tokens=False)
                                    # 检测常见结束标志
                                    if any(marker in temp_decoded for marker in ['。', '\n', '\r', '.', '！', '？']):
                                        break
                                except:
                                    pass
                        
                        # 3. 只解码“新生成的部分”作为翻译结果
                        gen_ids = curr_ids[prompt_len:]
                        if not gen_ids:
                            translated = ""
                        else:
                            token_arr = np.array([gen_ids], dtype=np.int64)
                            translated = self._decode_tokens(token_arr)
                        
                        batch_results.append(TranslationResult(
                            original=text,
                            translated=translated or text,
                        ))
                    
                    except Exception as e:
                        logger.error(f"Translation failed for '{text}': {e}")
                        # 失败时返回原文，避免整批报错
                        batch_results.append(TranslationResult(
                            original=text,
                            translated=text,
                        ))
                
                results.extend(batch_results)
            
            if progress_callback:
                progress_callback(len(texts), len(texts), "翻译完成")
            
            return AIResult(status=AIResultStatus.SUCCESS, data=results)
            
        except Exception as e:
            logger.error(f"HY-MT1.5 ONNX translation failed: {e}", exc_info=True)
            return AIResult(
                status=AIResultStatus.ERROR,
                error=str(e)
            )
    
    def _build_prompt(self, text: str, source_lang: str, target_lang: str) -> str:
        """
        按照 HY-MT 官方 README 中的提示词模板构建输入。
        
        - 当中英文互译（任一语言为中文）时，使用中文模板：
          “将以下文本翻译为{target_language}，注意只需要输出翻译后的结果，不要额外解释：\\n\\n{text}”
        - 其它语种之间互译时，使用英文模板：
          “Translate the following segment into {target_language}, without additional explanation.\\n\\n{text}”
        
        这里的 source_lang / target_lang 可能是语言代码（如 "en"）或中文名称（如 "简体中文"），
        所以需要做一层规范化，而不是直接把原始文件名丢给模型。
        """
        raw_target = (target_lang or "").strip()
        raw_source = (source_lang or "").strip()
        
        # 判断是否涉及中文（ZH <=> XX 使用中文模板）
        def _is_chinese_label(label: str) -> bool:
            lower = label.lower()
            return (
                "zh" in lower
                or "chinese" in lower
                or "中文" in label
                or "简体" in label
                or "繁体" in label
            )
        
        use_zh_template = _is_chinese_label(raw_target) or _is_chinese_label(raw_source)
        
        if use_zh_template:
            # 目标语言中文名称，用于插入中文提示词
            if "繁" in raw_target or "traditional" in raw_target.lower():
                target_display = "繁体中文"
            else:
                target_display = "中文"
            
            return f"将以下文本翻译为{target_display}，注意只需要输出翻译后的结果，不要额外解释：\\n\\n{text}"
        
        # 其它语种之间互译：使用英文模板，并将目标语言规范化为英文名称
        target_display = self._normalize_target_language_name(raw_target)
        return (
            f"Translate the following segment into {target_display}, without additional explanation.\\n\\n{text}"
        )
    
    def _normalize_target_language_name(self, target_lang: str) -> str:
        """
        将 UI / 代码中可能出现的目标语言表示规范化为模型 README 中使用的英文名称。
        如果无法识别，则直接返回原始字符串，保证不会因为映射失败而影响使用。
        """
        key = (target_lang or "").strip().lower()
        
        mapping = {
            # 中文在上游已经走中文模板，这里只是兜底
            "zh": "Chinese",
            "zh-cn": "Chinese",
            "zh-hans": "Chinese",
            "简体中文".lower(): "Chinese",
            "中文".lower(): "Chinese",
            "chinese": "Chinese",
            # 英语
            "en": "English",
            "english": "English",
            "英语".lower(): "English",
            # 日语
            "ja": "Japanese",
            "japanese": "Japanese",
            "日语".lower(): "Japanese",
            # 韩语
            "ko": "Korean",
            "korean": "Korean",
            "韩语".lower(): "Korean",
            # 俄语
            "ru": "Russian",
            "russian": "Russian",
            "俄语".lower(): "Russian",
            # 德语
            "de": "German",
            "german": "German",
            "德语".lower(): "German",
            # 法语
            "fr": "French",
            "french": "French",
            "法语".lower(): "French",
            # 西班牙语
            "es": "Spanish",
            "spanish": "Spanish",
            "西班牙语".lower(): "Spanish",
            # 其它常见语种（只做简单映射）
            "pt": "Portuguese",
            "portuguese": "Portuguese",
            "葡萄牙语".lower(): "Portuguese",
            "it": "Italian",
            "italian": "Italian",
            "意大利语".lower(): "Italian",
            "vi": "Vietnamese",
            "vietnamese": "Vietnamese",
            "越南语".lower(): "Vietnamese",
            "th": "Thai",
            "thai": "Thai",
            "泰语".lower(): "Thai",
        }
        
        return mapping.get(key, target_lang or "Chinese")
    
    def _build_step_inputs(
        self,
        token_ids: List[int],
        model_inputs: dict,
        max_length: int = 128,
    ) -> tuple[dict, int]:
        """
        为自回归生成的单步前向构建输入张量。
        
        为了简化逻辑，这里不复用 past_key_values，而是每一步都把
        当前完整序列送入模型，仅取最后一个位置的 logits。
        
        优化：使用较小的 max_length（128）以减少计算量，文件名翻译场景足够。
        """
        if not token_ids:
            raise ValueError("token_ids is empty")
        
        # 只保留末尾 max_length 个 token，避免不必要的计算
        if len(token_ids) > max_length:
            token_ids = token_ids[-max_length:]
        seq_len = len(token_ids)
        
        pad_len = max_length - seq_len
        pad_token_id = 0
        
        # 优化：预分配数组，减少列表拼接开销
        padded_ids = token_ids + [pad_token_id] * pad_len
        input_ids = np.array([padded_ids], dtype=np.int64)
        # 优化：使用更高效的 attention_mask 构建方式
        attention_mask = np.zeros((1, max_length), dtype=np.int64)
        attention_mask[0, :seq_len] = 1
        
        inputs: dict[str, np.ndarray] = {}
        for name, meta in model_inputs.items():
            ort_type = meta.type
            if ort_type == "tensor(int64)":
                dtype = np.int64
            elif ort_type == "tensor(int32)":
                dtype = np.int32
            elif ort_type in ("tensor(float16)", "tensor(float)"):
                dtype = np.float16 if "16" in ort_type else np.float32
            else:
                continue
            
            # 将动态维度统一替换为 1，后续再根据需要调整
            shape = []
            for dim in meta.shape:
                if isinstance(dim, int) and dim > 0:
                    shape.append(dim)
                else:
                    shape.append(1)
            
            if name == "input_ids":
                inputs[name] = input_ids.astype(dtype)
            elif name == "attention_mask":
                inputs[name] = attention_mask.astype(dtype)
            elif name == "position_ids":
                # [1, seq_len] 位置编码：0..seq_len-1，其余 padding 位置填 0
                # 优化：直接创建，避免不必要的切片操作
                pos = np.zeros((1, max_length), dtype=np.int64)
                pos[0, :seq_len] = np.arange(seq_len, dtype=np.int64)
                inputs[name] = pos.astype(dtype)
            elif name.startswith("past_key_values"):
                arr = np.zeros(shape, dtype=dtype)
                inputs[name] = arr
            else:
                arr = np.zeros(shape, dtype=dtype)
                inputs[name] = arr
        
        return inputs, seq_len
    
    async def cleanup(self) -> None:
        """清理资源"""
        self._session = None
        self._tokenizer = None
        logger.info("HY-MT1.5 ONNX service cleaned up")
