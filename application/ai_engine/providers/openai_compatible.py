"""
OpenAI Compatible Service

通用的OpenAI兼容API服务实现。
支持并发执行、频率限制控制和自动重试。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Dict, List, Optional

import aiohttp

from transcriptionist_v3.core.config import AppConfig

from ..base import (
    AIResult,
    AIResultStatus,
    AIServiceConfig,
    ProgressCallback,
    TranslationResult,
    TranslationService,
)

logger = logging.getLogger(__name__)



# 恢复独立的 Basic 模式提示词
BASIC_TRANSLATION_PROMPT = """
### Role
You are a professional sound effect translator.

### Task
Translate the given audio filenames from {{SOURCE_LANG}} to {{TARGET_LANG}}.

### Rules
1. **Format**: Do NOT include file extensions. Output ONLY the translated filename stem.
2. **Conciseness**: Output ONLY the translated name.
3. **Terminology**: Use standard audio post-production terminology.

### Output Format
Return a valid JSON object:
{
  "results": [
    {"original": "Explosion", "translated": "{{TARGET_LANG_EXAMPLE}}"}
  ]
}

{{LANGUAGE_ENFORCEMENT}}
"""

# 恢复独立的 Expert UCS 模式提示词
EXPERT_UCS_PROMPT = """
### Role
You are a UCS (Universal Category System) expert and sound supervisor.

### Task
Analyze the filename and output a structured UCS-compliant translation in {{TARGET_LANG}}.

### Rules
1. **UCS & Terminology**: Adhere to UCS standards for categorization.
2. **Analysis**: Break down the filename into Category, Subcategory, and Descriptor.
3. **Translation Scope**: 
   - Translate the Descriptor/Content to {{TARGET_LANG}}.
   - **CRITICAL**: If {{TARGET_LANG}} is NOT English, you MUST ALSO translate the Category and Subcategory into {{TARGET_LANG}} to ensure the entire filename is in the target language.
   - Example (Chinese): EXPLOSION -> 爆炸, BOMB -> 炸弹.

### Output Format
Return a valid JSON object:
{
  "results": [
    {
      "original": "Explosion_Bomb_Close_01",
      "category": "爆炸",
      "subcategory": "炸弹",
      "descriptor": "近距离",
      "translated": "{{TARGET_LANG_EXAMPLE}}",
      "variation": "01"
    }
  ]
}

{{LANGUAGE_ENFORCEMENT}}
"""


# 语言强制指令模板
LANGUAGE_ENFORCEMENT_TEMPLATES = {
    "Traditional Chinese": """
**CRITICAL LANGUAGE REQUIREMENT**:
- You MUST output all translations in Traditional Chinese characters (繁體中文).
- DO NOT use Simplified Chinese (简体中文) under any circumstances.
- Examples of correct output: 爆炸→爆炸, 脚步→腳步, 机械→機械
""",
    "Simplified Chinese": """
**IMPORTANT LANGUAGE REQUIREMENT**:
- You MUST output all translations in Simplified Chinese characters (简体中文).
""",
    "Japanese": """
**IMPORTANT LANGUAGE REQUIREMENT**:
- You MUST output all translations in Japanese (日本語).
- Use appropriate Kanji, Hiragana, or Katakana as suitable for audio effect terminology.
- Example: Explosion → 爆発, Footsteps → 足音
""",
    "Korean": """
**IMPORTANT LANGUAGE REQUIREMENT**:
- You MUST output all translations in Korean (한국어).
- Example: Explosion → 폭발, Footsteps → 발소리
""",
    "English": """
**IMPORTANT LANGUAGE REQUIREMENT**:
- You MUST output all translations in English.
- Use concise, professional audio terminology.
"""
}

# 目标语言示例映射 (用于 JSON 输出格式中的占位符)
TARGET_LANG_EXAMPLES = {
    "Simplified Chinese": "爆炸",
    "Traditional Chinese": "爆炸",
    "Japanese": "爆発",
    "Korean": "폭발",
    "English": "Explosion"
}

# 文件夹翻译提示词
FOLDER_TRANSLATION_PROMPT = """
### Role
You are a professional sound effect library organizer.

### Task
Translate the given folder names from {{SOURCE_LANG}} to {{TARGET_LANG}}.

### Rules
1. **Conciseness**: Output ONLY the translated folder name, no explanations.
2. **Terminology**: Use standard audio post-production terminology for categories.
3. **Common Categories**: 
   - Animals → 动物类
   - Household → 家庭杂物  
   - Weapons → 武器
   - Footsteps → 脚步声
   - Ambience → 环境音

### Output Format
Return a valid JSON object:
{
  "results": [
    {"original": "Animals", "translated": "{{TARGET_LANG_EXAMPLE}}"}
  ]
}

{{LANGUAGE_ENFORCEMENT}}
"""

# 默认降级提示词 (保持向后兼容)
DEFAULT_TRANSLATION_PROMPT = BASIC_TRANSLATION_PROMPT



class OpenAICompatibleService(TranslationService):
    """
    OpenAI兼容API服务
    
    支持并发请求、频率限制控制和自动退避重试。
    """
    
    SERVICE_ID = "openai_compatible"
    SERVICE_NAME = "OpenAI Compatible"
    SERVICE_DESC = "通用OpenAI兼容API服务"
    
    def __init__(self, config: AIServiceConfig):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None
        # 根据服务商设置并发限制
        self._concurrency_limit = self._get_concurrency_limit(config.provider_id)
        self._semaphore = asyncio.Semaphore(self._concurrency_limit)
        logger.info(f"Initialized {config.provider_id} service with concurrency limit: {self._concurrency_limit}")
    
    def _get_concurrency_limit(self, provider_id: str) -> int:
        """根据供应商分配并发上限"""
        # 允许通过全局配置覆盖（设置页中的“AI翻译并发数”）
        override = AppConfig.get("ai.translate_concurrency", None)
        if isinstance(override, int) and override >= 1:
            return override

        limits = {
            "deepseek": 20,    # 默认高并发
            "doubao": 20,
            "volcengine": 20,
            "openai": 5,       # 默认为 Tier 1 安全限制
        }
        return limits.get(provider_id, 2)
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取HTTP会话"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=90) # Increased timeout to 90 seconds
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
    
    async def cleanup(self) -> None:
        """清理资源"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    def _get_api_url(self) -> str:
        """获取API URL"""
        base_url = self._config.base_url.strip().rstrip("/")
        
        # 自动修正常见错误路径（如 /v8, /v2, /v3）
        if base_url.endswith("/v8") or base_url.endswith("/v2") or base_url.endswith("/v3"):
            logger.warning(f"Detected incorrect API version path in base_url: {base_url}, correcting to /v1")
            base_url = base_url.rsplit("/", 1)[0] + "/v1"
        
        # 如果 base_url 已经包含 /chat/completions，直接返回
        if "/chat/completions" in base_url:
            return base_url
        
        # 确保 base_url 以 /v1 结尾（兼容 Ollama/LM Studio）
        if not base_url.endswith("/v1"):
            # 如果 base_url 以 /v 开头但版本号不对，修正为 /v1
            if "/v" in base_url:
                base_url = base_url.rsplit("/v", 1)[0] + "/v1"
            else:
                # 如果没有版本号，添加 /v1
                base_url = f"{base_url}/v1"
        
        return f"{base_url}/chat/completions"
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头。Ollama 文档要求传 Authorization 但会忽略值，传 Bearer ollama 以兼容。"""
        headers = {"Content-Type": "application/json"}
        if self._config.api_key and self._config.api_key.strip():
            headers["Authorization"] = f"Bearer {self._config.api_key.strip()}"
        elif (self._config.provider_id or "").lower() == "local":
            headers["Authorization"] = "Bearer ollama"
        return headers
    
    def _get_system_prompt(self) -> str:
        """获取System Prompt"""
        return self._config.system_prompt or DEFAULT_TRANSLATION_PROMPT

    async def test_connection(self) -> AIResult[bool]:
        """测试API连接"""
        try:
            session = await self._get_session()
            
            payload = {
                "model": self._config.model_name,
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 5,
            }
            
            async with session.post(
                self._get_api_url(),
                headers=self._get_headers(),
                json=payload,
            ) as response:
                if response.status == 200:
                    return AIResult(status=AIResultStatus.SUCCESS, data=True)
                
                error_text = await response.text()
                error_msg = self._parse_error(response.status, error_text)
                return AIResult(
                    status=AIResultStatus.ERROR,
                    data=False,
                    error=error_msg,
                )
                
        except asyncio.TimeoutError:
            return AIResult(status=AIResultStatus.ERROR, data=False, error="连接超时")
        except Exception as e:
            logger.exception("Connection test failed")
            return AIResult(status=AIResultStatus.ERROR, data=False, error=str(e))
    
    def _parse_error(self, status_code: int, error_text: str) -> str:
        """解析错误信息"""
        try:
            error_data = json.loads(error_text)
            error_msg = error_data.get("error", {}).get("message", error_text)
        except json.JSONDecodeError:
            error_msg = error_text[:200]
        
        # 本地模型常见错误
        if status_code == 404:
            if "local" in self._config.provider_id.lower():
                return f"模型未找到或服务未启动 (404): {error_msg}\n请检查：\n1. Ollama/LM Studio 是否已启动\n2. 模型名称是否正确\n3. Base URL 是否正确"
            return f"资源未找到 (404): {error_msg}"
        elif status_code == 401:
            return "API Key 无效（本地模型通常不需要 API Key）"
        elif status_code == 429:
            return "触发频率限制 (Rate Limit)"
        elif status_code == 0 or "Connection" in error_msg or "Failed to fetch" in error_msg:
            # 连接错误（通常是本地服务未启动）
            if "local" in self._config.provider_id.lower():
                return f"无法连接到本地服务: {error_msg}\n请检查：\n1. Ollama/LM Studio 是否已启动\n2. Base URL：LM Studio 默认 http://localhost:1234/v1，Ollama 默认 http://localhost:11434/v1\n3. 防火墙是否阻止了连接"
            return f"连接失败: {error_msg}"
        else:
            return f"API错误 ({status_code}): {error_msg}"

    async def translate_batch(
        self,
        texts: List[str],
        source_lang: str = "en",
        target_lang: str = "zh",
        progress_callback: Optional[ProgressCallback] = None,
    ) -> AIResult[List[TranslationResult]]:
        """
        并发批量翻译
        采用 Semaphore 控制并发路数，分组发送请求。
        """
        if not texts:
            return AIResult(status=AIResultStatus.SUCCESS, data=[])
        
        # 将长列表分成小批次：可通过配置调整 (ai.translate_chunk_size)
        configured_chunk = AppConfig.get("ai.translate_chunk_size", 40)
        try:
            configured_chunk = int(configured_chunk)
        except (TypeError, ValueError):
            configured_chunk = 40
        # 限制在合理区间内，避免设置过小/过大
        if configured_chunk < 5:
            logger.warning(f"translate_chunk_size {configured_chunk} is too small, clamping to 5")
            configured_chunk = 5
        if configured_chunk > 200:
            logger.warning(f"translate_chunk_size {configured_chunk} is too large, clamping to 200")
            configured_chunk = 200

        chunk_size = configured_chunk
        chunks = [texts[i:i + chunk_size] for i in range(0, len(texts), chunk_size)]
        logger.info(f"translate_batch: split {len(texts)} texts into {len(chunks)} chunks (chunk_size={chunk_size})")
        
        # 动态读取并发数配置（每次调用时都重新读取，支持运行时修改）
        current_concurrency = self._get_concurrency_limit(self._config.provider_id)
        # 如果并发数改变了，更新 semaphore
        if current_concurrency != self._concurrency_limit:
            logger.info(f"Concurrency limit changed from {self._concurrency_limit} to {current_concurrency}, updating semaphore")
            self._concurrency_limit = current_concurrency
            self._semaphore = asyncio.Semaphore(self._concurrency_limit)
        
        # 统计变量
        progress_data = {"completed": 0, "total": len(texts)}
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        
        logger.info(f"translate_batch: processing {len(texts)} texts in {len(chunks)} chunks (chunk_size={chunk_size}, concurrency={current_concurrency})")
        
        async def process_chunk(chunk: List[str], batch_idx: int) -> List[TranslationResult]:
            logger.debug(f"process_chunk[{batch_idx}]: waiting for semaphore, chunk size={len(chunk)}")
            async with self._semaphore:
                logger.info(f"process_chunk[{batch_idx}]: acquired semaphore, starting translation of {len(chunk)} items")
                # 带有退避重试的请求
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        session = await self._get_session()
                        
                        user_content = f"""Translate the following audio filenames to Chinese JSON array:
{json.dumps(chunk, ensure_ascii=False)}"""
                        
                        payload = {
                            "model": self._config.model_name.strip(),
                            "messages": [
                                {"role": "system", "content": self._get_system_prompt()},
                                {"role": "user", "content": user_content},
                            ],
                            "temperature": self._config.temperature,
                            "max_tokens": self._config.max_tokens,
                        }
                        
                        # Ollama / LM Studio 均支持 streaming 与 response_format（OpenAI 兼容）
                        if self._config.provider_id in ("deepseek", "openai", "local"):
                            payload["response_format"] = {"type": "json_object"}
                            payload["stream"] = True
                            
                            async with session.post(
                                self._get_api_url(),
                                headers=self._get_headers(),
                                json=payload,
                            ) as response:
                                if response.status == 429:
                                    delay = (2 ** attempt) + random.random()
                                    logger.warning(f"Rate limited (429) on batch {batch_idx+1}, attempt {attempt+1}/{max_retries}, retrying in {delay:.2f}s...")
                                    await asyncio.sleep(delay)
                                    continue
                                
                                if response.status >= 500:
                                    delay = (2 ** attempt) + random.random()
                                    logger.warning(f"Server error ({response.status}) on batch {batch_idx+1}, attempt {attempt+1}/{max_retries}, retrying in {delay:.2f}s...")
                                    await asyncio.sleep(delay)
                                    continue
                                    
                                if not response.ok:
                                    error_text = await response.text()
                                    logger.error(f"Batch {batch_idx+1} failed with {response.status}: {error_text[:200]}")
                                    if attempt < max_retries - 1:
                                        delay = 2 + random.random()
                                        await asyncio.sleep(delay)
                                        continue
                                    else:
                                        return [TranslationResult(original=t, translated=t) for t in chunk]
                                
                                # 流式响应处理
                                content = ""
                                item_count = 0
                                last_progress_update = 0
                                stream_done = False
                                
                                try:
                                    async for line in response.content:
                                        line_str = line.decode('utf-8').strip()
                                        if not line_str:
                                            continue
                                        
                                        # 检查流结束标志
                                        if line_str == "data: [DONE]":
                                            stream_done = True
                                            logger.debug(f"process_chunk[{batch_idx}]: received [DONE] signal")
                                            break
                                        
                                        if line_str.startswith("data: "):
                                            try:
                                                chunk_data = json.loads(line_str[6:])
                                                delta = chunk_data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                                if delta:
                                                    content += delta
                                                    # 启发式进度更新：检测 "translated" 字段或简单的行数/结构
                                                    # 简单方案：统计 "translated" 出现的次数 (虽然不一定完全准确，但足够给用户反馈)
                                                    # 为了避免重复计数，我们只在 content 增长时检查
                                                    current_count = content.count('"translated"')
                                                    if current_count > item_count:
                                                        new_items = current_count - item_count
                                                        item_count = current_count
                                                        
                                                        # 更新全局进度
                                                        progress_data["completed"] += new_items
                                                        # 确保不超过总数（因为最后还会校准）
                                                        if progress_data["completed"] > progress_data["total"]:
                                                            progress_data["completed"] = progress_data["total"] - 1
                                                            
                                                        if progress_callback:
                                                            progress_callback(
                                                                progress_data["completed"], 
                                                                progress_data["total"], 
                                                                f"正在翻译: {progress_data['completed']}/{progress_data['total']}"
                                                            )
                                            except json.JSONDecodeError as e:
                                                logger.debug(f"process_chunk[{batch_idx}]: JSON decode error in stream: {e}")
                                                pass
                                    
                                    # 如果没有收到 [DONE] 信号，记录警告
                                    if not stream_done:
                                        logger.warning(f"process_chunk[{batch_idx}]: stream ended without [DONE] signal, content length={len(content)}")
                                except asyncio.TimeoutError:
                                    logger.error(f"process_chunk[{batch_idx}]: stream timeout while reading response")
                                    raise
                                except Exception as e:
                                    logger.error(f"process_chunk[{batch_idx}]: error reading stream: {e}", exc_info=True)
                                    raise
                                
                                # 解析最终完整JSON
                                if not content:
                                    logger.warning(f"process_chunk[{batch_idx}]: empty content received, using fallback")
                                    return [TranslationResult(original=t, translated=t) for t in chunk]
                                
                                results = self._parse_translation_response(content, chunk)
                                logger.info(f"process_chunk[{batch_idx}]: completed, translated {len(results)}/{len(chunk)} items")
                                
                                # 进度校准：补齐这一批次剩余的计数
                                # (如果 heuristics 漏掉了，或者最后 parse 出来比统计的多)
                                final_batch_count = len(chunk)
                                # 这一批次之前贡献了多少进度？ item_count
                                # 现在不管之前加了多少，我们都要确保这一批完成后，progress_data增加的总量等于 len(chunk)
                                # 但由于 progress_data["completed"] 是全局共享的，我们在上面已经加了 item_count
                                # 所以现在要加的是 (final_batch_count - item_count)
                                
                                remaining = final_batch_count - item_count
                                if remaining > 0:
                                    progress_data["completed"] += remaining
                                    if progress_callback:
                                        progress_callback(
                                            progress_data["completed"], 
                                            progress_data["total"], 
                                            f"完成批次: {progress_data['completed']}/{progress_data['total']}"
                                        )
                                
                                # 确保返回的结果数量与输入一致
                                if len(results) != len(chunk):
                                    logger.warning(f"process_chunk[{batch_idx}]: result count mismatch: got {len(results)}, expected {len(chunk)}")
                                    # 补齐缺失的结果
                                    while len(results) < len(chunk):
                                        idx = len(results)
                                        results.append(TranslationResult(original=chunk[idx], translated=chunk[idx]))
                                
                                return results
                            
                    except asyncio.TimeoutError:
                        logger.error(f"Timeout on batch {batch_idx+1}, attempt {attempt+1}/{max_retries}")
                        if attempt < max_retries - 1:
                            delay = (2 ** attempt) + random.random()
                            await asyncio.sleep(delay)
                            continue
                    except Exception as e:
                        logger.error(f"Error in batch {batch_idx+1}, attempt {attempt+1}/{max_retries}: {e}")
                        if attempt < max_retries - 1:
                            delay = (2 ** attempt) + random.random()
                            await asyncio.sleep(delay)
                            continue
                
                return [TranslationResult(original=t, translated=t) for t in chunk]

        # 并发执行所有切片
        logger.info(f"Starting {len(chunks)} concurrent tasks with concurrency limit {current_concurrency}")
        tasks = [process_chunk(chunk, i) for i, chunk in enumerate(chunks)]
        chunk_results = await asyncio.gather(*tasks)
        logger.info(f"All {len(chunks)} chunks completed")
        
        # 合并结果
        all_results = []
        for res_list in chunk_results:
            all_results.extend(res_list)
            
        return AIResult(
            status=AIResultStatus.SUCCESS,
            data=all_results,
            usage=total_usage,
        )
    
    def _parse_translation_response(self, content: str, original_texts: List[str]) -> List[TranslationResult]:
        """解析翻译响应，带有格式错误的恢复逻辑"""
        results = []
        result_map = {}
        
        try:
            # 1. 基础清理
            clean_content = content.strip()
            if "```" in clean_content:
                import re
                match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_content)
                if match:
                    clean_content = match.group(1)
            
            # 2. 尝试标准 JSON 解析
            try:
                parsed = json.loads(clean_content)
                items = []
                if isinstance(parsed, list):
                    items = parsed
                elif isinstance(parsed, dict):
                    # 寻找可能的数组字段 ("results" 是由于提示词要求的)
                    items = parsed.get("results", [])
                    if not items:
                        for v in parsed.values():
                            if isinstance(v, list):
                                items = v
                                break
                
                for item in items:
                    if not isinstance(item, dict): continue
                    orig = item.get("original", "")
                    if orig:
                        result_map[orig] = TranslationResult(
                            original=orig,
                            translated=item.get("translated", ""),
                            category=item.get("category"),
                            subcategory=item.get("subcategory"),
                            descriptor=item.get("descriptor"),
                            variation=item.get("variation")
                        )
            except json.JSONDecodeError as je:
                logger.warning(f"Standard JSON parse failed, attempting regex recovery: {je}")
                # 3. 容错逻辑：使用正则表达式从损坏的文本中抢救数据
                import re
                # 匹配 {"original": "...", "translated": "...", ...} 模式
                # 即使 JSON 列表没闭合，或者中间缺逗号，只要单条记录相对完整就能提取
                obj_pattern = re.compile(r'\{[^{}]*"original"\s*:\s*"([^"]*)"[^{}]*"translated"\s*:\s*"([^"]*)"[^{}]*\}')
                matches = obj_pattern.finditer(clean_content)
                
                recovery_count = 0
                for match in matches:
                    orig_val = match.group(1)
                    trans_val = match.group(2)
                    if orig_val and orig_val not in result_map:
                        # 进一步尝试提取 UCS 字段 (可选)
                        cat_m = re.search(r'"category"\s*:\s*"([^"]*)"', match.group(0))
                        sub_m = re.search(r'"subcategory"\s*:\s*"([^"]*)"', match.group(0))
                        desc_m = re.search(r'"descriptor"\s*:\s*"([^"]*)"', match.group(0))
                        var_m = re.search(r'"variation"\s*:\s*"([^"]*)"', match.group(0))
                        
                        result_map[orig_val] = TranslationResult(
                            original=orig_val,
                            translated=trans_val,
                            category=cat_m.group(1) if cat_m else None,
                            subcategory=sub_m.group(1) if sub_m else None,
                            descriptor=desc_m.group(1) if desc_m else None,
                            variation=var_m.group(1) if var_m else None
                        )
                        recovery_count += 1
                
                if recovery_count > 0:
                    logger.info(f"Successfully recovered {recovery_count} items from malformed JSON via regex")
                else:
                    logger.error("Regex recovery failed to find any valid translation pairs")

            # 4. 校准结果，确保返回数量与输入一致
            for text in original_texts:
                if text in result_map:
                    results.append(result_map[text])
                else:
                    # 如果翻译彻底丢失，回退到原名
                    results.append(TranslationResult(original=text, translated=text))
                
        except Exception as e:
            logger.error(f"Critical error in _parse_translation_response: {e}", exc_info=True)
            results = [TranslationResult(original=t, translated=t) for t in original_texts]
            
        return results

    async def translate(self, text: str, source_lang: str = "en", target_lang: str = "zh") -> AIResult[TranslationResult]:
        res = await self.translate_batch([text], source_lang, target_lang)
        if res.success and res.data:
            return AIResult(status=res.status, data=res.data[0], usage=res.usage)
        return AIResult(status=AIResultStatus.ERROR, error=res.error)

    async def translate_single(self, text: str) -> AIResult[str]:
        """
        通用单文本翻译/生成 (跳过 JSON 包装逻辑，直接请求)
        用于搜索词翻译、标签翻译等非文件名场景。
        """
        try:
            session = await self._get_session()
            
            payload = {
                "model": self._config.model_name,
                "messages": [
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": text}
                ],
                "temperature": self._config.temperature,
                "max_tokens": self._config.max_tokens,
            }
            
            # 移除 JSON 模式强制 (如果之前有设置)
            
            async with session.post(
                self._get_api_url(),
                headers=self._get_headers(),
                json=payload,
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    content = data["choices"][0]["message"]["content"]
                    return AIResult(status=AIResultStatus.SUCCESS, data=content)
                else:
                    error_text = await response.text()
                    return AIResult(status=AIResultStatus.ERROR, data="", error=f"HTTP {response.status}: {error_text}")
                    
        except Exception as e:
            logger.error(f"translate_single failed: {e}")
            return AIResult(status=AIResultStatus.ERROR, data="", error=str(e))
