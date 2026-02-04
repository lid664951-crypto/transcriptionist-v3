"""
UCS (Universal Category System) 标签加载

内置影视音效标签集（UCS v8.2.1 英文），供 AI 智能打标使用。
数据来自 ucs_labels_data.UCS_DATA，无需外部 xlsx 文件。

- 对外提供的是每条条目的 explanation 字段（英文自然语言描述），
  CLAP 模型可直接理解并做语义匹配；打标后由 AI 将英文标签译为中文展示。
"""

from __future__ import annotations

from typing import List


def get_builtin_ucs_english_labels() -> List[str]:
    """
    返回内置 UCS 影视音效标签集（英文自然语言描述）。

    每条对应 ucs_labels_data.UCS_DATA 的 explanation 字段，格式为完整英文句子
    （如 "Steady air blows, like from a compressed can of air."），
    CLAP 能正确理解语义；翻译为中文时由提示词说明其为影视音效行业专业术语。
    """
    from transcriptionist_v3.ui.utils.ucs_labels_data import UCS_DATA
    return [item["explanation"] for item in UCS_DATA]
