"""
Tag Generator

标签生成服务，从文件名和音频特征生成标签。
"""

from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass

from .base import (
    AIResult,
    AIResultStatus,
    AIServiceConfig,
    ProgressCallback,
    TagGenerationService,
    TagResult,
)

logger = logging.getLogger(__name__)


# ============================================================
# 预定义的标签词库
# ============================================================

# 音效类型标签
SOUND_TYPE_TAGS = {
    # 环境音
    "ambience": ["环境音", "氛围"],
    "ambient": ["环境音", "氛围"],
    "atmo": ["环境音", "氛围"],
    "atmosphere": ["环境音", "氛围"],
    "room_tone": ["房间音", "环境音"],
    
    # 拟音
    "foley": ["拟音"],
    "footstep": ["脚步声", "拟音"],
    "cloth": ["布料声", "拟音"],
    "movement": ["动作音", "拟音"],
    
    # 撞击音
    "impact": ["撞击", "打击"],
    "hit": ["打击", "撞击"],
    "punch": ["拳击", "打击"],
    "slam": ["猛击", "撞击"],
    "crash": ["碰撞", "撞击"],
    "thud": ["闷响", "撞击"],
    
    # 嗖声
    "whoosh": ["嗖声", "过渡"],
    "swish": ["嗖声"],
    "swoosh": ["嗖声"],
    "sweep": ["扫频", "过渡"],
    
    # 界面音
    "ui": ["界面音", "UI"],
    "click": ["点击", "界面音"],
    "button": ["按钮", "界面音"],
    "notification": ["通知", "界面音"],
    "alert": ["提示", "界面音"],
    "beep": ["蜂鸣", "界面音"],
    
    # 转场
    "transition": ["转场", "过渡"],
    "riser": ["上升音", "转场"],
    "rise": ["上升音"],
    "drop": ["下降音", "转场"],
    "stinger": ["刺针音", "转场"],
    
    # 爆炸
    "explosion": ["爆炸"],
    "blast": ["爆炸", "冲击"],
    "boom": ["轰鸣", "爆炸"],
    "detonate": ["爆炸"],
    
    # 武器
    "weapon": ["武器"],
    "gun": ["枪声", "武器"],
    "gunshot": ["枪声"],
    "rifle": ["步枪", "武器"],
    "pistol": ["手枪", "武器"],
    "sword": ["剑", "武器"],
    "knife": ["刀", "武器"],
    
    # 载具
    "vehicle": ["载具"],
    "car": ["汽车", "载具"],
    "engine": ["引擎", "机械"],
    "motor": ["马达", "机械"],
    "helicopter": ["直升机", "载具"],
    "airplane": ["飞机", "载具"],
    
    # 自然
    "nature": ["自然"],
    "wind": ["风声", "自然"],
    "rain": ["雨声", "自然"],
    "thunder": ["雷声", "自然"],
    "water": ["水声", "自然"],
    "fire": ["火焰", "自然"],
    "forest": ["森林", "自然"],
    "ocean": ["海洋", "自然"],
    
    # 动物
    "animal": ["动物"],
    "bird": ["鸟", "动物"],
    "dog": ["狗", "动物"],
    "cat": ["猫", "动物"],
    "horse": ["马", "动物"],
    "insect": ["昆虫", "动物"],
    
    # 人声
    "voice": ["人声"],
    "vocal": ["人声"],
    "scream": ["尖叫", "人声"],
    "laugh": ["笑声", "人声"],
    "crowd": ["人群", "人声"],
    
    # 机械
    "mechanical": ["机械"],
    "machine": ["机器", "机械"],
    "metal": ["金属", "机械"],
    "gear": ["齿轮", "机械"],
    "servo": ["伺服", "机械"],
    
    # 电子
    "electronic": ["电子"],
    "synth": ["合成器", "电子"],
    "digital": ["数字", "电子"],
    "glitch": ["故障音", "电子"],
    "static": ["静电", "电子"],
    "buzz": ["嗡嗡声", "电子"],
    
    # 恐怖
    "horror": ["恐怖"],
    "scary": ["恐怖"],
    "creepy": ["诡异", "恐怖"],
    "dark": ["黑暗", "恐怖"],
    "tension": ["紧张", "恐怖"],
    
    # 科幻
    "scifi": ["科幻"],
    "sci-fi": ["科幻"],
    "space": ["太空", "科幻"],
    "laser": ["激光", "科幻"],
    "alien": ["外星", "科幻"],
    "robot": ["机器人", "科幻"],
    
    # 魔法/奇幻
    "magic": ["魔法", "奇幻"],
    "spell": ["咒语", "魔法"],
    "fantasy": ["奇幻"],
    "mystical": ["神秘", "奇幻"],
}

# 情感/氛围标签
MOOD_TAGS = {
    "happy": ["欢快", "积极"],
    "sad": ["悲伤", "忧郁"],
    "angry": ["愤怒", "激烈"],
    "calm": ["平静", "舒缓"],
    "tense": ["紧张", "悬疑"],
    "epic": ["史诗", "宏大"],
    "soft": ["柔和", "轻柔"],
    "hard": ["硬朗", "强烈"],
    "fast": ["快速"],
    "slow": ["缓慢"],
    "loud": ["响亮"],
    "quiet": ["安静", "轻柔"],
    "bright": ["明亮"],
    "dark": ["黑暗", "阴沉"],
}

# 技术属性标签
TECH_TAGS = {
    "loop": ["循环"],
    "one_shot": ["单次"],
    "oneshot": ["单次"],
    "stereo": ["立体声"],
    "mono": ["单声道"],
    "surround": ["环绕声"],
    "dry": ["干声"],
    "wet": ["湿声"],
    "processed": ["处理过"],
    "raw": ["原始"],
    "clean": ["干净"],
    "distorted": ["失真"],
}


class FilenameTagExtractor:
    """
    从文件名提取标签
    
    解析文件名中的关键词，匹配预定义标签库。
    """
    
    def __init__(self):
        # 合并所有标签词库
        self._tag_map: Dict[str, List[str]] = {}
        self._tag_map.update(SOUND_TYPE_TAGS)
        self._tag_map.update(MOOD_TAGS)
        self._tag_map.update(TECH_TAGS)
    
    def extract(self, filename: str) -> List[str]:
        """从文件名提取标签"""
        # 移除扩展名
        name = Path(filename).stem
        
        # 分词：按下划线、连字符、空格、驼峰分割
        tokens = self._tokenize(name)
        
        # 匹配标签
        tags: Set[str] = set()
        
        for token in tokens:
            token_lower = token.lower()
            
            # 直接匹配
            if token_lower in self._tag_map:
                tags.update(self._tag_map[token_lower])
            
            # 部分匹配（处理复合词）
            for key, values in self._tag_map.items():
                if key in token_lower or token_lower in key:
                    if len(key) >= 3 and len(token_lower) >= 3:
                        tags.update(values)
        
        # 提取数字编号
        numbers = re.findall(r'\d+', name)
        if numbers:
            tags.add(f"变体{len(numbers)}")
        
        return list(tags)
    
    def _tokenize(self, text: str) -> List[str]:
        """分词"""
        # 替换分隔符为空格
        text = re.sub(r'[_\-\s]+', ' ', text)
        
        # 处理驼峰命名
        text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
        
        # 分割并过滤
        tokens = text.split()
        tokens = [t.strip() for t in tokens if len(t.strip()) >= 2]
        
        return tokens


class AITagGenerator(TagGenerationService):
    """
    AI标签生成服务
    
    结合规则提取和AI生成标签。
    """
    
    SERVICE_ID = "tag_generator"
    SERVICE_NAME = "标签生成"
    SERVICE_DESC = "从文件名和音频特征生成标签"
    
    def __init__(self, config: AIServiceConfig):
        super().__init__(config)
        self._filename_extractor = FilenameTagExtractor()
        self._use_ai = bool(config.api_key)  # 有API Key时使用AI增强
    
    async def test_connection(self) -> AIResult[bool]:
        """测试连接"""
        return AIResult(status=AIResultStatus.SUCCESS, data=True)
    
    async def generate_tags(
        self,
        filename: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AIResult[TagResult]:
        """生成标签"""
        tags: Set[str] = set()
        
        # 1. 从文件名提取
        filename_tags = self._filename_extractor.extract(filename)
        tags.update(filename_tags)
        
        # 2. 从元数据提取
        if metadata:
            metadata_tags = self._extract_from_metadata(metadata)
            tags.update(metadata_tags)
        
        # 3. AI增强（可选）
        if self._use_ai and len(tags) < 3:
            # TODO: 调用AI服务生成更多标签
            pass
        
        return AIResult(
            status=AIResultStatus.SUCCESS,
            data=TagResult(tags=list(tags)),
        )
    
    async def generate_tags_batch(
        self,
        items: List[Dict[str, Any]],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> AIResult[List[TagResult]]:
        """批量生成标签"""
        results = []
        total = len(items)
        
        for i, item in enumerate(items):
            filename = item.get("filename", "")
            metadata = item.get("metadata")
            
            result = await self.generate_tags(filename, metadata)
            if result.success and result.data:
                results.append(result.data)
            else:
                results.append(TagResult(tags=[]))
            
            if progress_callback:
                progress_callback(i + 1, total, f"处理: {filename}")
        
        return AIResult(
            status=AIResultStatus.SUCCESS,
            data=results,
        )
    
    def _extract_from_metadata(self, metadata: Dict[str, Any]) -> List[str]:
        """从元数据提取标签"""
        tags = []
        
        # 从现有标签字段
        if "tags" in metadata:
            existing = metadata["tags"]
            if isinstance(existing, list):
                tags.extend(existing)
            elif isinstance(existing, str):
                tags.extend(existing.split(","))
        
        # 从genre字段
        if "genre" in metadata:
            tags.append(metadata["genre"])
        
        # 从comment字段提取关键词
        if "comment" in metadata:
            comment = metadata["comment"]
            # 简单提取
            words = re.findall(r'\b\w{3,}\b', comment)
            for word in words[:5]:  # 最多5个
                word_lower = word.lower()
                if word_lower in SOUND_TYPE_TAGS:
                    tags.extend(SOUND_TYPE_TAGS[word_lower])
        
        # 根据时长添加标签
        duration = metadata.get("duration_ms", 0)
        if duration > 0:
            if duration < 1000:
                tags.append("短音效")
            elif duration > 30000:
                tags.append("长音效")
        
        return tags


class TagManager:
    """
    标签管理器
    
    管理标签生成和标签库。
    """
    
    _instance: Optional['TagManager'] = None
    
    def __init__(self):
        self._generator: Optional[AITagGenerator] = None
        self._custom_tags: Dict[str, List[str]] = {}  # 用户自定义标签映射
    
    @classmethod
    def instance(cls) -> 'TagManager':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def configure(self, config: Optional[AIServiceConfig] = None) -> None:
        """配置标签生成器"""
        if config is None:
            config = AIServiceConfig(provider_id="tag_generator")
        self._generator = AITagGenerator(config)
    
    async def generate_tags(
        self,
        filename: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """生成标签"""
        if self._generator is None:
            self.configure()
        
        result = await self._generator.generate_tags(filename, metadata)
        if result.success and result.data:
            return result.data.tags
        return []
    
    async def generate_tags_batch(
        self,
        items: List[Dict[str, Any]],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> List[List[str]]:
        """批量生成标签"""
        if self._generator is None:
            self.configure()
        
        result = await self._generator.generate_tags_batch(items, progress_callback)
        if result.success and result.data:
            return [tr.tags for tr in result.data]
        return [[] for _ in items]
    
    def add_custom_mapping(self, keyword: str, tags: List[str]) -> None:
        """添加自定义标签映射"""
        self._custom_tags[keyword.lower()] = tags
    
    def get_all_categories(self) -> List[str]:
        """获取所有标签分类"""
        categories = set()
        for tags in SOUND_TYPE_TAGS.values():
            categories.update(tags)
        return sorted(categories)
