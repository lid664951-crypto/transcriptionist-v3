import logging
import asyncio
import re
from typing import Optional

from transcriptionist_v3.core.config import AppConfig
from transcriptionist_v3.application.ai_engine.base import AIServiceConfig

logger = logging.getLogger(__name__)

class MusicGenPromptOptimizer:
    """
    MusicGen 提示词优化器
    Core Mission: 将用户输入的中文/口语化描述转化为 MusicGen 友好的英文专业提示词
    """
    
    SYSTEM_PROMPT = (
        "You are an expert music and sound effects prompt engineer for MusicGen AI.\n"
        "Your task is to convert the user's description (in any language) into "
        "a precise English prompt that MusicGen can understand.\n"
        "Rules:\n"
        "1. Output ONLY the English prompt, no explanations.\n"
        "2. Use professional music/audio terminology (e.g., 'whoosh' not '呼呼声').\n"
        "3. Include mood, tempo, instruments, and style when relevant.\n"
        "4. Keep it concise (under 50 words).\n"
        "5. Remove filler words like 'I want', 'please generate', etc.\n"
        "Examples:\n"
        "- '欢快的钢琴曲' -> 'cheerful piano melody with upbeat tempo and bright tones'\n"
        "- '紧张的电影配乐' -> 'intense cinematic soundtrack with dramatic strings'\n"
        "- '呼呼的转场声' -> 'whoosh swish transition sound effect'"
    )
    
    def __init__(self):
        self._loop = None
        
    def _get_ai_config(self) -> Optional[AIServiceConfig]:
        """获取当前激活的 AI 配置"""
        try:
            api_key = AppConfig.get("ai.api_key", "").strip()
            if not api_key:
                logger.warning("No AI API key found for prompt optimization")
                return None
                
            model_index = AppConfig.get("ai.model_index", 0)
            model_configs = {
                0: {"provider": "deepseek", "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
                1: {"provider": "openai", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
                2: {"provider": "doubao", "model": "doubao-pro-4k", "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
            }
            config_data = model_configs.get(model_index, model_configs[0])
            
            return AIServiceConfig(
                provider_id=config_data['provider'],
                model_name=config_data['model'],
                api_key=api_key,
                base_url=config_data['base_url'],
                temperature=0.3,
                max_tokens=60
            )
        except Exception as e:
            logger.error(f"Failed to get AI config: {e}")
            return None

    async def _optimize_async(self, user_input: str) -> str:
        """异步执行优化"""
        import aiohttp
        
        config = self._get_ai_config()
        if not config:
            return user_input
            
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": config.model_name,
                    "messages": [
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": user_input}
                    ],
                    "temperature": 0.3
                }
                headers = {
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json"
                }
                
                async with session.post(
                    f"{config.base_url}/chat/completions",
                    json=payload, 
                    headers=headers,
                    timeout=10
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data['choices'][0]['message']['content'].strip()
                        # 清理可能存在的引号
                        return content.replace('"', '').replace("'", "")
                    else:
                        logger.warning(f"Optimization API error: {resp.status}")
                        return user_input
                        
        except Exception as e:
            logger.error(f"Prompt optimization failed: {e}")
            return user_input

    def optimize(self, user_input: str) -> str:
        """
        优化提示词 (同步调用封装)
        
        Args:
            user_input: 用户输入的原始文本 (中文/英文)
            
        Returns:
            str: MusicGen 友好的英文提示词
        """
        # 1. 简单规则过滤：如果是简短英文，直接返回
        if re.match(r'^[a-zA-Z0-9\s,\.]+$', user_input) and len(user_input.split()) < 5:
            return user_input
            
        # 2. 调用 AI 优化
        try:
            # 在现有的事件循环中运行，或者创建新的
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 如果已经在循环中，这里比较麻烦，通常 UI 线程不是 Loop
                    # 在 Qt 环境中，通常可以在后台线程运行
                    import threading
                    if threading.current_thread() is threading.main_thread():
                        # 在主线程，虽然不推荐阻塞，但为了简化集成...
                        pass
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            return loop.run_until_complete(self._optimize_async(user_input))
            
        except Exception as e:
            logger.error(f"Sync optimization wrapper failed: {e}")
            return user_input
