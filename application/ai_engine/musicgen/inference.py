
import logging
import time
import json
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Any, Union, Tuple

import onnxruntime as ort
import soundfile as sf
from tokenizers import Tokenizer

from .paths import get_models_dir

logger = logging.getLogger(__name__)

class MusicGenInference:
    """
    MusicGen ONNX 推理引擎
    
    负责：
    1. 加载 ONNX 模型 (支持 CPU/DirectML/CUDA)
    2. 执行文本转音频推理
    3. 音频后处理 (解码)
    """
    
    SAMPLE_RATE = 32000
    MAX_NEW_TOKENS = 1500  # ~30s at 50 tokens/sec
    
    def __init__(self, use_gpu: bool = True):
        self.models_dir = get_models_dir()
        self.use_gpu = use_gpu
        self._sessions: Dict[str, ort.InferenceSession] = {}
        self._tokenizer: Optional[Tokenizer] = None
        
        # 验证模型文件是否存在
        required_files = [
            "text_encoder_fp16.onnx",
            "decoder_model_fp16.onnx",  # 标准无缓存解码器
            "encodec_decode_fp16.onnx",
            "config.json",
            "tokenizer.json"
        ]
        missing = [f for f in required_files if not (self.models_dir / f).exists()]
        if missing:
            raise FileNotFoundError(f"Missing model files: {missing}")
        
        # Load config
        self._load_config()
            
    def _load_config(self):
        """加载模型配置"""
        config_path = self.models_dir / "config.json"
        with open(config_path, 'r', encoding='utf-8') as f:
            self._config = json.load(f)
        logger.info(f"Loaded config: {self._config.get('model_type', 'unknown')}")
            
    def _create_session(self, model_name: str) -> 'ort.InferenceSession':
        """创建推理会话，自动选择最佳 Provider"""
        model_path = str(self.models_dir / model_name)
        
        providers = []
        if self.use_gpu:
            # 优先顺序: CUDA -> DirectML -> CPU
            if 'CUDAExecutionProvider' in ort.get_available_providers():
                providers.append('CUDAExecutionProvider')
            elif 'DmlExecutionProvider' in ort.get_available_providers():
                providers.append('DmlExecutionProvider')
        
        providers.append('CPUExecutionProvider')
        
        logger.info(f"Loading {model_name} with providers: {providers}")
        try:
            session = ort.InferenceSession(model_path, providers=providers)
            active_provider = session.get_providers()[0]
            logger.info(f"Loaded {model_name} using {active_provider}")
            return session
        except Exception as e:
            logger.error(f"Failed to load {model_name}: {e}")
            # Fallback to CPU if failed
            if 'CPUExecutionProvider' not in providers:
                logger.warning("Retrying with CPUExecutionProvider...")
                return ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
            raise e

    def load_models(self):
        """预加载所有模型 (耗时操作)"""
        logger.info("Pre-loading MusicGen models...")
        self._sessions['text_encoder'] = self._create_session("text_encoder_fp16.onnx")
        
        # Revert to standard session creation (DML/GPU if available)
        # Now that input shapes are fixed (2D instead of 3D), DML should work.
        # The CPU crash was due to FP16 model optimizations incompatible with CPU implementation.
        logger.info("Loading decoder_model_fp16.onnx")
        self._sessions['decoder'] = self._create_session("decoder_model_fp16.onnx")
        
        # Force CPU for EnCodec - DML has issues with Pad operations in this model
        logger.info("Loading encodec_decode_fp16.onnx (Forced CPU due to DML Pad node incompatibility)")
        self._sessions['encodec_decode'] = ort.InferenceSession(
            str(self.models_dir / "encodec_decode_fp16.onnx"),
            providers=['CPUExecutionProvider']
        )
        
        # 打印解码器输入输出信息用于调试
        decoder_session = self._sessions['decoder']
        logger.info(f"Decoder inputs: {[inp.name for inp in decoder_session.get_inputs()]}")
        logger.info(f"Decoder outputs: {[out.name for out in decoder_session.get_outputs()]}")

        # Write Debug Info
        try:
             with open(r"C:\Users\DELL\Desktop\musicgen_debug_model.txt", "w", encoding="utf-8") as f:
                 f.write("=== Decoder Inputs ===\n")
                 for inp in self._sessions['decoder'].get_inputs():
                     f.write(f"Name: {inp.name}, Shape: {inp.shape}, Type: {inp.type}\n")
        except:
            pass
        
        logger.info("All models loaded successfully")
    
    def _load_tokenizer(self):
        """加载真实的 T5 tokenizer"""
        tokenizer_path = self.models_dir / "tokenizer.json"
        if not tokenizer_path.exists():
            raise FileNotFoundError(f"Tokenizer file not found: {tokenizer_path}")
        
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        logger.info(f"Loaded tokenizer from {tokenizer_path}")
        
    def _tokenize(self, text: str) -> np.ndarray:
        """使用真实的 T5 tokenizer 进行分词"""
        if not self._tokenizer:
            self._load_tokenizer()
        
        # Tokenize using the real T5 tokenizer
        encoding = self._tokenizer.encode(text)
        token_ids = encoding.ids
        
        # Reshape for ONNX model (batch_size=1, sequence_length)
        return np.array([token_ids], dtype=np.int64)

    def generate(self, prompt: str, duration: int = 10, guidance_scale: float = 3.0, callback=None) -> Tuple[int, np.ndarray]:
        """
        生成音频 (Real ONNX Implementation)
        
        Args:
            prompt: 英文提示词
            duration: 时长 (秒)
            guidance_scale: CFG 强度 (1.0=无CFG, 3.0=官方推荐, 越大越遵循文本)
            callback: 进度回调 (percent, msg)
            
        Returns:
            (sample_rate, audio_waveform)
        """
        try:
            if not self._sessions:
                if callback:
                    callback(0, "加载模型...")
                self.load_models()
            
            logger.info(f"Generating audio for: '{prompt}' ({duration}s)")
            
            # Step 1: Tokenize and encode text
            if callback:
                callback(10, "编码文本...")
            text_embeddings, attention_mask = self._encode_text(prompt)
            
            # Step 2: Calculate number of tokens to generate
            num_tokens = int(duration * 50)  # ~50 tokens per second
            num_tokens = min(num_tokens, self.MAX_NEW_TOKENS)
            
            # Step 3: Autoregressive generation
            if callback:
                callback(20, "生成音频编码...")
            audio_codes = self._generate_codes(
                text_embeddings, 
                num_tokens, 
                callback, 
                attention_mask=attention_mask,
                guidance_scale=guidance_scale
            )
            
            # Step 4: Decode to waveform
            if callback:
                callback(90, "解码音频波形...")
            audio_waveform = self._decode_audio(audio_codes)
            
            if callback:
                callback(100, "完成")
            
            logger.info(f"Generation complete: {audio_waveform.shape}")
            return self.SAMPLE_RATE, audio_waveform
            
        except Exception as e:
            import traceback
            error_msg = f"Generation failed: {e}\n{traceback.format_exc()}"
            logger.error(error_msg)
            
            # Write to desktop for debugging
            try:
                with open(r"C:\Users\DELL\Desktop\musicgen_error.txt", "w", encoding="utf-8") as f:
                    f.write(error_msg)
            except:
                pass
                
            # Fallback to mock for testing
            logger.warning("Falling back to mock generation")
            return self._mock_generate(prompt, duration, callback)
    
    def _mock_generate(self, prompt: str, duration: int, callback=None) -> Tuple[int, np.ndarray]:
        """Mock generation fallback"""
        if callback:
            callback(50, "使用模拟模式生成...")
        time.sleep(2)
        t = np.linspace(0, duration, int(self.SAMPLE_RATE * duration), False)
        audio_data = 0.5 * np.sin(2 * np.pi * 440 * t) + 0.3 * np.sin(2 * np.pi * 554 * t)
        return self.SAMPLE_RATE, audio_data.astype(np.float32)
    
    def _encode_text(self, prompt: str) -> Tuple[np.ndarray, np.ndarray]:
        """使用 T5 编码器编码文本"""
        # Tokenize
        input_ids = self._tokenize(prompt)
        
        # Create attention mask (1 for token, 0 for padding)
        # Since we just have one input without padding, it's all 1s
        attention_mask = np.ones_like(input_ids, dtype=np.int64)
        
        # Run text encoder
        session = self._sessions['text_encoder']
        
        # Get input names dynamically
        input_names = [inp.name for inp in session.get_inputs()]
        inputs = {}
        
        # Map inputs based on what the model expects
        inputs['input_ids'] = input_ids
        if 'attention_mask' in input_names:
            inputs['attention_mask'] = attention_mask
            
        outputs = session.run(None, inputs)
        
        # Return last hidden state and mask
        return outputs[0], attention_mask
    
    def continue_audio(self, audio_data: np.ndarray, prompt: str, duration: int = 5, callback=None) -> Tuple[int, np.ndarray]:
        """
        音频续写
        
        Args:
            audio_data: 输入音频数据 (SAMPLE_RATE, 1)
            prompt: 文本提示词
            duration: 续写时长
        """
        try:
            if not self._sessions:
                if callback:
                    callback(0, "加载模型...")
                self.load_models()
                
            # Step 0: Encode Audio to Tokens
            if callback:
                callback(10, "编码参考音频...")
            audio_codes = self._encode_audio(audio_data)
            
            # Step 1: Encode Text
            # Note: continue_audio also needs to handle the mask if we want it to be robust, 
            # but for now let's update _encode_text first.
            text_embeddings, attention_mask = self._encode_text(prompt)
            
            # Step 2: Generate
            num_tokens = int(duration * 50)
            if callback:
                callback(20, "生成续写...")
            
            # Pass audio_codes as initial prompt (decoder input)
            # MusicGen expects conditioning on audio codes for continuation
            generated_codes = self._generate_codes(text_embeddings, num_tokens, callback, audio_prompt=audio_codes, attention_mask=attention_mask)
            
            # Step 3: Decode
            if callback:
                callback(90, "解码音频...")
            waveform = self._decode_audio(generated_codes)
            
            if callback:
                callback(100, "完成")
            return self.SAMPLE_RATE, waveform
            
        except Exception as e:
            logger.error(f"Continuation failed: {e}")
            return self._mock_generate(prompt, duration, callback)

    def _encode_audio(self, audio_data: np.ndarray) -> np.ndarray:
        """使用 EnCodec 编码音频为 Tokens"""
        session = self._sessions['encodec_encode']
        # Reshape: [1, 1, samples]
        if audio_data.ndim == 1:
            audio_data = audio_data[np.newaxis, np.newaxis, :]
        
        inputs = {session.get_inputs()[0].name: audio_data.astype(np.float32)}
        outputs = session.run(None, inputs)
        # Output: [1, 4, seq_len] (Codes)
        return outputs[0].astype(np.int64)

    def _generate_codes(self, text_embeddings: np.ndarray, num_tokens: int, callback=None, audio_prompt: np.ndarray = None, attention_mask: np.ndarray = None, guidance_scale: float = 3.0) -> np.ndarray:
        """自回归生成音频编码 (WITH Classifier-Free Guidance)"""
        session = self._sessions['decoder']
        
        # Get input names dynamically
        input_names = [inp.name for inp in session.get_inputs()]
        
        batch_size = 1
        num_codebooks = 4
        
        # DEBUG: Write input debug info to desktop
        try:
            with open(r"C:\Users\DELL\Desktop\musicgen_debug.txt", "w", encoding="utf-8") as f:
                f.write(f"Num Tokens: {num_tokens}\n")
                f.write(f"Input Names: {input_names}\n")
                f.write(f"Guidance Scale: {guidance_scale}\n")
                if audio_prompt is not None:
                    f.write(f"Audio Prompt Shape: {audio_prompt.shape}\n")
        except:
            pass
        
        # Prepare unconditional embeddings (zeros) for CFG
        unconditional_embeddings = np.zeros_like(text_embeddings)
        unconditional_mask = np.zeros_like(attention_mask) if attention_mask is not None else None
        
        # Initialize
        if audio_prompt is not None:
            generated_codes = audio_prompt
        else:
            generated_codes = np.zeros((batch_size, num_codebooks, 0), dtype=np.int64)
            
        # Autoregressive loop
        for i in range(num_tokens):
            if callback and i % 5 == 0:
                progress = 20 + int((i / num_tokens) * 70)
                callback(progress, f"生成中 {i}/{num_tokens} tokens...")
            
            # Prepare input_ids: Flatten [1, 4, seq_len] -> [4, seq_len]
            if generated_codes.shape[2] == 0:
                 curr_codes_flat = np.zeros((num_codebooks, 1), dtype=np.int64) 
            else:
                 curr_codes_flat = generated_codes.reshape(num_codebooks, -1)

            try:
                # === Classifier-Free Guidance: Run decoder TWICE ===
                
                # 1. Conditional forward (with text)
                cond_inputs = {
                    'input_ids': curr_codes_flat,
                    'encoder_hidden_states': text_embeddings,
                }
                if attention_mask is not None:
                    cond_inputs['encoder_attention_mask'] = attention_mask
                
                cond_outputs = session.run(None, cond_inputs)
                cond_logits = cond_outputs[0][:, -1, :]  # [4, vocab_size]
                
                # 2. Unconditional forward (no text, zeros)
                uncond_inputs = {
                    'input_ids': curr_codes_flat,
                    'encoder_hidden_states': unconditional_embeddings,
                }
                if unconditional_mask is not None:
                    uncond_inputs['encoder_attention_mask'] = unconditional_mask
                
                uncond_outputs = session.run(None, uncond_inputs)
                uncond_logits = uncond_outputs[0][:, -1, :]  # [4, vocab_size]
                
                # 3. Apply CFG formula: logits = uncond + guidance_scale * (cond - uncond)
                guided_logits = uncond_logits + guidance_scale * (cond_logits - uncond_logits)
                
                # 4. Sample from the guided logits
                temperature = 1.0
                top_k = 250
                
                # Apply temperature
                scaled_logits = guided_logits / temperature
                
                # Apply top-k filtering
                top_k_values = np.partition(scaled_logits, -top_k, axis=-1)[:, -top_k:]
                threshold = np.min(top_k_values, axis=1, keepdims=True)
                scaled_logits = np.where(scaled_logits < threshold, -np.inf, scaled_logits)
                
                # Convert to probabilities
                exp_logits = np.exp(scaled_logits - np.max(scaled_logits, axis=-1, keepdims=True))
                probs = exp_logits / np.sum(exp_logits, axis=-1, keepdims=True)
                
                # Sample from the distribution
                next_code = np.array([np.random.choice(probs.shape[1], p=probs[codebook]) 
                                     for codebook in range(4)])  # [4]
                
                # Reshape back to [1, 4, 1] for concatenation
                next_code = next_code.reshape(1, 4, 1)
                
                # Append to sequence
                generated_codes = np.concatenate([generated_codes, next_code], axis=2)
                
            except Exception as e:
                logger.warning(f"Decoder step {i} failed: {e}")
                # DEBUG: Write error to desktop (Limit to first 5 errors to avoid massive I/O)
                if i < 5:
                    try:
                        with open(r"C:\Users\DELL\Desktop\musicgen_debug.txt", "a", encoding="utf-8") as f:
                            f.write(f"Step {i} Failed: {e}\n")
                    except:
                        pass
                
                # Stop generation on first error
                logger.error("Stopping generation due to repeated errors.")
                break 
        
        return generated_codes
    
    def _decode_audio(self, audio_codes: np.ndarray) -> np.ndarray:
        """使用 EnCodec 解码器将编码转换为波形"""
        session = self._sessions['encodec_decode']
        
        # EnCodec 期望 4D 输入: [batch, 1, codebooks, seq_len]
        # 当前生成的是 3D: [batch, codebooks, seq_len]
        if audio_codes.ndim == 3:
            audio_codes = audio_codes[:, np.newaxis, :, :]  # 添加维度
        
        # Prepare input
        inputs = {session.get_inputs()[0].name: audio_codes.astype(np.int64)}
        
        # DEBUG: Log EnCodec input shape
        try:
            with open(r"C:\Users\DELL\Desktop\musicgen_encodec_debug.txt", "w", encoding="utf-8") as f:
                f.write(f"EnCodec Input Shape: {audio_codes.shape}\n")
                f.write(f"EnCodec Input Dtype: {audio_codes.dtype}\n")
                f.write(f"Expected Input: {session.get_inputs()[0].name}, Shape: {session.get_inputs()[0].shape}\n")
        except:
            pass
        
        try:
            outputs = session.run(None, inputs)
            waveform = outputs[0].squeeze()
            
            # Normalize
            if np.abs(waveform).max() > 0:
                waveform = waveform / np.abs(waveform).max()
            
            return waveform.astype(np.float32)
        except Exception as e:
            logger.error(f"Audio decoding failed: {e}")
            # Return silence as fallback
            return np.zeros(self.SAMPLE_RATE * 5, dtype=np.float32)

    def unload(self):
        """释放模型内存"""
        self._sessions.clear()
        import gc
        gc.collect()
