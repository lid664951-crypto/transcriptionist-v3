
import os
import logging
import json
import numpy as np
from pathlib import Path
from typing import List, Optional, Union

# Third-party imports
try:
    import onnxruntime as ort
    import librosa
    from tokenizers import Tokenizer
except ImportError as e:
    logging.getLogger(__name__).warning(f"AI dependencies missing: {e}")

logger = logging.getLogger(__name__)

class CLAPInferenceService:
    """
    Service for running CLAP model inference using ONNX Runtime with DirectML.
    Handles audio/text preprocessing and embedding generation.
    """
    
    # Standard CLAP HTSAT configurations
    SAMPLE_RATE = 48000
    N_FFT = 1024
    HOP_LENGTH = 480
    N_MELS = 64
    WINDOW_SIZE = 1024
    MAX_LENGTH_SECONDS = 10  # CLAP typically trains on 10s chunks
    
    def __init__(self, model_dir: Union[str, Path]):
        self.model_dir = Path(model_dir)
        self.session: Optional[ort.InferenceSession] = None
        self.tokenizer: Optional[Tokenizer] = None
        self._is_ready = False
        
    def initialize(self) -> bool:
        """Load model and tokenizer"""
        if self._is_ready:
            return True
            
        try:
            onnx_path = self.model_dir / "onnx" / "model.onnx"
            vocab_path = self.model_dir / "vocab.json" # or tokenizer.json
            
            if not onnx_path.exists():
                logger.error(f"Model not found at {onnx_path}")
                return False
                
            # 1. Load Tokenizer
            # Try loading tokenizer.json first, then vocab.json
            tokenizer_path = self.model_dir / "tokenizer.json"
            if tokenizer_path.exists():
                self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
            elif vocab_path.exists():
                # Fallback or specific loader might be needed for vocab.json only
                # For now assume tokenizer.json exists as downloaded by worker
                logger.warning("tokenizer.json not found, attempting legacy load or skipping")
                return False
            
            # 2. Load ONNX Session with DirectML
            providers = ['DmlExecutionProvider', 'CPUExecutionProvider']
            self.session = ort.InferenceSession(str(onnx_path), providers=providers)
            
            logger.info(f"CLAP Model loaded successfully. Device: {self.session.get_providers()[0]}")
            self._is_ready = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize CLAP service: {e}", exc_info=True)
            return False

    def get_text_embedding(self, text: str) -> Optional[np.ndarray]:
        """Generate embedding for text query"""
        if not self._is_ready or not self.tokenizer:
            return None
            
        try:
            # Tokenize
            encoded = self.tokenizer.encode(text)
            input_ids = np.array([encoded.ids], dtype=np.int64)
            attention_mask = np.array([encoded.attention_mask], dtype=np.int64)
            
            inputs = {
                "input_ids": input_ids,
                "attention_mask": attention_mask
            }
            
            # Check model inputs dynamically
            model_inputs = [i.name for i in self.session.get_inputs()]
            
            # CRITICAL FIX: Provide dummy audio input if model requires it (for unfused/combined graphs)
            if "input_features" in model_inputs:
                # Shape: (Batch, 1, Time, Freq) -> (1, 1, 1001, 64)
                # Time = 1001 derived from (10s * 48000) / 480 hop + 1
                # Zeros are fine for "no audio"
                dummy_audio = np.zeros((1, 1, 1001, 64), dtype=np.float32)
                inputs["input_features"] = dummy_audio

            # Run inference
            outputs = self.session.run(None, inputs)
            
            # Extract text embedding
            output_names = [o.name for o in self.session.get_outputs()]
            
            # Look for specific text embedding output
            if "text_embeds" in output_names:
                idx = output_names.index("text_embeds")
                return outputs[idx][0]
            
            # Fallback for some exports
            return outputs[0][0]
            
        except Exception as e:
            logger.error(f"Text embedding failed: {e}")
            return None

    def get_audio_embedding(self, audio_path: str) -> Optional[np.ndarray]:
        """Generate embedding for audio file"""
        if not self._is_ready:
            return None
            
        try:
            # 1. Preprocess Audio
            mel_log = self._preprocess_audio(audio_path)
            if mel_log is None:
                return None
            
            # Feature formatting: (Batch, Channel, Height, Width) -> (1, 1, 1001, 64)
            input_features = mel_log[np.newaxis, np.newaxis, :, :]
            input_features = input_features.transpose(0, 1, 3, 2)
            
            # 2. Run inference
            return self._run_audio_inference(input_features)
            
        except Exception as e:
            logger.error(f"Audio embedding failed: {e}")
            return None

    def get_audio_embeddings_batch(self, audio_paths: list[str], batch_size: int = 4) -> dict[str, np.ndarray]:
        """
        Generate embeddings for multiple audio files in batches (OPTIMIZED with multiprocessing)
        
        Args:
            audio_paths: List of audio file paths
            batch_size: Number of files to process in one GPU batch (default: 4)
            
        Returns:
            Dictionary mapping file paths to embeddings
        """
        if not self._is_ready:
            return {}
        
        # 从配置读取 CPU 进程数
        from transcriptionist_v3.core.config import AppConfig
        cpu_processes = AppConfig.get("ai.cpu_processes", None)
        
        # 如果没有配置，自动检测
        if cpu_processes is None:
            import os
            cpu_count = os.cpu_count() or 4
            if cpu_count >= 16:
                cpu_processes = 8
            elif cpu_count >= 8:
                cpu_processes = cpu_count - 2
            else:
                cpu_processes = max(1, cpu_count - 1)
        
        logger.info(f"Using {cpu_processes} CPU processes for audio preprocessing")
        
        results = {}
        
        # 使用多进程预处理音频
        if cpu_processes > 1 and len(audio_paths) > 1:
            try:
                from multiprocessing import Pool
                
                # 多进程预处理
                with Pool(processes=cpu_processes) as pool:
                    mel_results = pool.map(self._preprocess_audio, audio_paths)
                
                # 过滤失败的结果
                valid_mels = []
                valid_paths = []
                for path, mel_log in zip(audio_paths, mel_results):
                    if mel_log is not None:
                        valid_mels.append(mel_log)
                        valid_paths.append(path)
                
                if not valid_mels:
                    return {}
                
                # 批量 GPU 推理
                for i in range(0, len(valid_mels), batch_size):
                    batch_mels = valid_mels[i:i + batch_size]
                    batch_paths = valid_paths[i:i + batch_size]
                    
                    # Stack into batch
                    batch_features = np.stack([
                        mel[np.newaxis, :, :] for mel in batch_mels
                    ], axis=0)
                    
                    # Transpose to correct format
                    batch_features = batch_features.transpose(0, 1, 3, 2)
                    
                    # Run batch inference
                    embeddings = self._run_audio_inference(batch_features)
                    
                    # Map results back to paths
                    if embeddings is not None:
                        if embeddings.ndim == 1:
                            results[batch_paths[0]] = embeddings
                        else:
                            for path, emb in zip(batch_paths, embeddings):
                                results[path] = emb
                
                return results
                
            except Exception as e:
                logger.error(f"Multiprocessing failed: {e}, falling back to single process")
                # Fall through to single process mode
        
        # 单进程模式（原有逻辑）
        for i in range(0, len(audio_paths), batch_size):
            batch_paths = audio_paths[i:i + batch_size]
            
            try:
                # 1. Preprocess all audio files in batch
                mel_features = []
                valid_paths = []
                
                for path in batch_paths:
                    mel_log = self._preprocess_audio(path)
                    if mel_log is not None:
                        mel_features.append(mel_log)
                        valid_paths.append(path)
                
                if not mel_features:
                    continue
                
                # 2. Stack into batch: (batch_size, 1, time_steps, n_mels)
                batch_features = np.stack([
                    mel[np.newaxis, :, :] for mel in mel_features
                ], axis=0)
                
                # Transpose to correct format: (batch_size, 1, time_steps, n_mels)
                batch_features = batch_features.transpose(0, 1, 3, 2)
                
                # 3. Run batch inference
                embeddings = self._run_audio_inference(batch_features)
                
                # 4. Map results back to paths
                if embeddings is not None:
                    if embeddings.ndim == 1:
                        # Single result
                        results[valid_paths[0]] = embeddings
                    else:
                        # Multiple results
                        for path, emb in zip(valid_paths, embeddings):
                            results[path] = emb
                
            except Exception as e:
                logger.error(f"Batch embedding failed for batch {i//batch_size}: {e}")
                # Fall back to individual processing for this batch
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
        Preprocess a single audio file to mel spectrogram
        
        Returns:
            Mel spectrogram of shape (n_mels, time_steps) or None if failed
        """
        try:
            # 检查文件格式
            file_ext = Path(audio_path).suffix.lower()
            
            # 对于 MP4 文件，先检查是否是视频文件
            if file_ext in ['.mp4', '.m4v', '.mov']:
                try:
                    import mutagen
                    audio_file = mutagen.File(audio_path)
                    
                    # 检查是否有音频流
                    if audio_file is None:
                        logger.warning(f"Skipping {Path(audio_path).name}: Not a valid audio/video file")
                        return None
                    
                    # 检查是否有视频流（MP4 特有）
                    if hasattr(audio_file, 'info') and hasattr(audio_file.info, 'codec'):
                        codec = str(audio_file.info.codec).lower()
                        if 'video' in codec or 'h264' in codec or 'h265' in codec:
                            logger.info(f"Skipping {Path(audio_path).name}: Video file (use audio extraction tool first)")
                            return None
                except Exception as e:
                    logger.debug(f"Format check failed for {Path(audio_path).name}, trying to load anyway: {e}")
            
            # Load and resample
            y, sr = librosa.load(audio_path, sr=self.SAMPLE_RATE)
            
            # Mix to mono
            if y.ndim > 1:
                y = np.mean(y, axis=0)
                
            # Pad or Truncate to MAX_LENGTH (10s => 480,000 samples)
            target_len = self.SAMPLE_RATE * self.MAX_LENGTH_SECONDS
            if len(y) > target_len:
                y = y[:target_len]
            else:
                y = np.pad(y, (0, target_len - len(y)), mode='constant')
                
            # Compute Mel Spectrogram
            mel = librosa.feature.melspectrogram(
                y=y, 
                sr=self.SAMPLE_RATE, 
                n_fft=self.N_FFT, 
                hop_length=self.HOP_LENGTH,
                n_mels=self.N_MELS,
                window='hann',
                center=True,
                pad_mode='reflect',
                power=2.0
            )
            
            # Log compress
            mel_log = librosa.power_to_db(mel, ref=np.max)
            
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

    def _run_audio_inference(self, input_features: np.ndarray) -> Optional[np.ndarray]:
        """
        Run ONNX inference on preprocessed audio features
        
        Args:
            input_features: Shape (batch_size, 1, time_steps, n_mels) or (1, 1, time_steps, n_mels)
            
        Returns:
            Embeddings of shape (batch_size, embed_dim) or (embed_dim,) for single input
        """
        try:
            # Prepare Inputs
            inputs = {
                "input_features": input_features.astype(np.float32)
            }

            # Check model inputs
            model_inputs = [i.name for i in self.session.get_inputs()]

            # CRITICAL FIX: Provide dummy text input if model requires it
            if "input_ids" in model_inputs:
                batch_size = input_features.shape[0]
                dummy_text = "audio"
                encoded = self.tokenizer.encode(dummy_text)
                # Repeat for batch
                inputs["input_ids"] = np.tile(
                    np.array([encoded.ids], dtype=np.int64), 
                    (batch_size, 1)
                )
                inputs["attention_mask"] = np.tile(
                    np.array([encoded.attention_mask], dtype=np.int64),
                    (batch_size, 1)
                )

            # Filter inputs to only what model expects
            feed_dict = {k: v for k, v in inputs.items() if k in model_inputs}
            
            # Run inference
            outputs = self.session.run(None, feed_dict)
             
            # Extract audio embedding
            output_names = [o.name for o in self.session.get_outputs()]
            
            if "audio_embeds" in output_names:
                idx = output_names.index("audio_embeds")
                embeddings = outputs[idx]
            elif len(outputs) > 1:
                embeddings = outputs[1]
            else:
                embeddings = outputs[0]
            
            # Return single embedding if batch_size == 1
            if embeddings.shape[0] == 1:
                return embeddings[0]
            return embeddings
            
        except Exception as e:
            logger.error(f"Audio inference failed: {e}")
            return None

    def classify_audio(self, audio_embedding: np.ndarray, candidate_labels: list[str], top_k: int = 3) -> list[tuple[str, float]]:
        """
        Perform zero-shot classification (tagging) for a given audio embedding.
        
        Args:
            audio_embedding: The audio embedding vector.
            candidate_labels: List of text labels to compare against.
            top_k: Number of top matches to return.
            
        Returns:
            List of (label, score) tuples, sorted by score descending.
        """
        if audio_embedding is None or not candidate_labels:
            return []
            
        scores = []
        for label in candidate_labels:
            # 1. Get text embedding for label
            text_embed = self.get_text_embedding(label)
            if text_embed is None:
                continue
                
            # 2. Compute Cosine Similarity
            # (A . B) / (|A| * |B|)
            norm_audio = np.linalg.norm(audio_embedding)
            norm_text = np.linalg.norm(text_embed)
            
            if norm_audio == 0 or norm_text == 0:
                sim = 0.0
            else:
                sim = np.dot(audio_embedding, text_embed) / (norm_audio * norm_text)
            
            scores.append((label, float(sim)))
            
        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        
        return scores[:top_k]
