#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
独立后台元数据提取脚本

此脚本作为独立进程运行，使用多进程并行提取音频文件元数据。
通过 JSON 文件进行输入/输出数据交换，避免在 GUI 进程中使用 multiprocessing。

使用方式:
    python metadata_worker.py --input <input.json> --output <output.json> [--workers N]

输入 JSON 格式:
    {
        "files": ["path1.wav", "path2.mp3", ...],
        "progress_file": "progress.json",  # 可选，用于报告进度
        "max_workers": 16,                 # 可选，并行进程上限（不传则用 CPU 检测，上限 64）
        "progress_interval": 500           # 可选，每处理多少文件写一次进度（不传则按 total 自动：max(50, min(5000, total//200))）
    }

输出 JSON 格式:
    {
        "results": [
            {"path": "path1.wav", "metadata": {...}},
            {"path": "path2.mp3", "metadata": null},
            ...
        ],
        "stats": {
            "total": 100,
            "success": 98,
            "failed": 2,
            "elapsed_seconds": 5.2
        }
    }

进度 JSON 格式（实时更新）:
    {
        "processed": 50,
        "total": 100,
        "current_file": "path50.wav",
        "status": "running"  # "running", "completed", "error"
    }
"""

import argparse
import json
import os
import sys
import time
import logging
from pathlib import Path
from multiprocessing import Pool, cpu_count
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, asdict

# 配置日志（静默模式，只记录错误）
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class MetadataResult:
    """元数据结果"""
    duration: Optional[float] = None
    sample_rate: Optional[int] = None
    bit_depth: Optional[int] = None
    channels: Optional[int] = None
    bitrate: Optional[int] = None
    format: Optional[str] = None
    comment: Optional[str] = None
    original_filename: Optional[str] = None


# 全局提取器实例（每个子进程一个）
_extractor_instance = None


def _get_extractor():
    """懒加载 MetadataExtractor 实例"""
    global _extractor_instance
    if _extractor_instance is None:
        try:
            from transcriptionist_v3.application.library_manager.metadata_extractor import MetadataExtractor
            _extractor_instance = MetadataExtractor()
        except ImportError:
            # 如果无法导入项目模块，使用内置的 mutagen 提取
            _extractor_instance = _FallbackExtractor()
    return _extractor_instance


class _FallbackExtractor:
    """回退提取器（当无法导入项目模块时使用）"""
    
    def __init__(self):
        try:
            import mutagen
            self._mutagen_available = True
        except ImportError:
            self._mutagen_available = False
    
    def extract(self, file_path: Path) -> Optional[MetadataResult]:
        """提取元数据"""
        if not self._mutagen_available:
            return None
        
        try:
            import mutagen
            audio = mutagen.File(file_path)
            if audio is None:
                return None
            
            result = MetadataResult()
            result.format = file_path.suffix.lstrip('.').lower()
            
            if hasattr(audio, 'info'):
                info = audio.info
                if hasattr(info, 'length'):
                    result.duration = float(info.length)
                if hasattr(info, 'sample_rate'):
                    result.sample_rate = int(info.sample_rate)
                if hasattr(info, 'channels'):
                    result.channels = int(info.channels)
                if hasattr(info, 'bits_per_sample'):
                    result.bit_depth = int(info.bits_per_sample)
                if hasattr(info, 'bitrate'):
                    result.bitrate = int(info.bitrate)
            
            return result
        except Exception:
            return None


def _extract_single_file(file_path_str: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    提取单个文件的元数据（供多进程调用）
    
    Args:
        file_path_str: 文件路径字符串
        
    Returns:
        (文件路径, 元数据字典或None)
    """
    try:
        extractor = _get_extractor()
        file_path = Path(file_path_str)
        
        metadata = extractor.extract(file_path)
        
        if metadata is None:
            return file_path_str, None
        
        # 转换为字典
        if hasattr(metadata, '__dict__'):
            # 项目的 AudioMetadata 对象
            meta_dict = {
                'duration': getattr(metadata, 'duration', None),
                'sample_rate': getattr(metadata, 'sample_rate', None),
                'bit_depth': getattr(metadata, 'bit_depth', None),
                'channels': getattr(metadata, 'channels', None),
                'bitrate': getattr(metadata, 'bitrate', None),
                'format': getattr(metadata, 'format', None),
                'comment': getattr(metadata, 'comment', None),
                'original_filename': getattr(metadata, 'original_filename', None),
            }
        elif isinstance(metadata, MetadataResult):
            meta_dict = asdict(metadata)
        else:
            meta_dict = dict(metadata) if hasattr(metadata, 'items') else None
        
        return file_path_str, meta_dict
        
    except Exception as e:
        logger.error(f"Error extracting {file_path_str}: {e}")
        return file_path_str, None


def _update_progress(progress_file: Optional[str], processed: int, total: int, 
                     current_file: str, status: str = "running"):
    """更新进度文件"""
    if not progress_file:
        return
    
    try:
        progress_data = {
            "processed": processed,
            "total": total,
            "current_file": current_file,
            "status": status
        }
        
        # 使用临时文件写入，然后原子重命名，避免读取到不完整的 JSON
        temp_file = progress_file + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, ensure_ascii=False)
        
        # Windows 上需要先删除目标文件
        if os.path.exists(progress_file):
            os.remove(progress_file)
        os.rename(temp_file, progress_file)
        
    except Exception:
        pass  # 进度更新失败不应中断主流程


def _compute_progress_interval(total: int, override: Optional[int]) -> int:
    """
    根据总文件数计算进度写入间隔（不硬编码）。
    超大批量（如百万级）时降频，避免进度文件写入过于频繁。
    """
    if override is not None and override > 0:
        return min(override, max(1, total // 10))
    # 约 50~5000 之间，随 total 缩放：百万条约 5000，十万条约 500
    return max(50, min(5000, total // 200))


def extract_metadata_parallel(
    file_paths: List[str],
    num_workers: Optional[int] = None,
    progress_file: Optional[str] = None,
    batch_size: int = 50,
    max_workers_cap: Optional[int] = None,
    progress_interval: Optional[int] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    并行提取多个文件的元数据。支持流式写入输出文件，避免百万级时内存爆掉。
    
    Args:
        file_paths: 文件路径列表
        num_workers: 工作进程数（默认 CPU 核心数 -1）
        progress_file: 进度文件路径（可选）
        batch_size: imap 每批任务数
        max_workers_cap: 进程数上限（不传则 64，由调用方根据 CPU 传入亦可）
        progress_interval: 每处理多少文件写一次进度（不传则按 total 自动）
        output_path: 若提供，则流式写入结果到此文件，不在内存中累积 results
        
    Returns:
        包含 results（仅当未流式写入时）和 stats 的字典；流式写入时 results 为空列表
    """
    if num_workers is None:
        num_workers = max(1, cpu_count() - 1)
    cap = 64 if max_workers_cap is None else max(1, min(max_workers_cap, 128))
    num_workers = min(num_workers, len(file_paths), cap)
    
    total = len(file_paths)
    interval = _compute_progress_interval(total, progress_interval)
    success_count = 0
    failed_count = 0
    start_time = time.time()
    results = []  # 仅在不流式写入时使用
    
    _update_progress(progress_file, 0, total, "", "running")
    
    try:
        out_file = None
        if output_path:
            out_file = open(output_path, 'w', encoding='utf-8')
            out_file.write('{"results": [')
        
        with Pool(processes=num_workers) as pool:
            first = True
            for i, (path, metadata) in enumerate(
                pool.imap_unordered(_extract_single_file, file_paths, chunksize=batch_size)
            ):
                if metadata is not None:
                    success_count += 1
                else:
                    failed_count += 1
                
                if out_file:
                    obj = {"path": path, "metadata": metadata}
                    out_file.write(('' if first else ',') + json.dumps(obj, ensure_ascii=False))
                    first = False
                else:
                    results.append({"path": path, "metadata": metadata})
                
                if (i + 1) % interval == 0 or (i + 1) == total:
                    _update_progress(progress_file, i + 1, total, path, "running")
        
        elapsed = time.time() - start_time
        _update_progress(progress_file, total, total, "", "completed")
        
        stats = {
            "total": total,
            "success": success_count,
            "failed": failed_count,
            "elapsed_seconds": round(elapsed, 2)
        }
        
        if out_file:
            out_file.write('], "stats": ' + json.dumps(stats, ensure_ascii=False) + '}\n')
            out_file.close()
            return {"results": [], "stats": stats}
        
        return {"results": results, "stats": stats}
        
    except Exception:
        if out_file:
            try:
                out_file.close()
            except Exception:
                pass
        _update_progress(progress_file, 0, total, "", "error")
        raise


def main():
    """主入口"""
    parser = argparse.ArgumentParser(
        description='并行提取音频文件元数据'
    )
    parser.add_argument(
        '--input', '-i',
        required=True,
        help='输入 JSON 文件路径'
    )
    parser.add_argument(
        '--output', '-o',
        required=True,
        help='输出 JSON 文件路径'
    )
    parser.add_argument(
        '--workers', '-w',
        type=int,
        default=None,
        help='工作进程数（默认为 CPU 核心数 - 1）'
    )
    
    args = parser.parse_args()
    
    try:
        # 读取输入
        with open(args.input, 'r', encoding='utf-8') as f:
            input_data = json.load(f)
        
        file_paths = input_data.get('files', [])
        progress_file = input_data.get('progress_file')
        max_workers = input_data.get('max_workers')  # 可选，由主程序根据 CPU 传入
        progress_interval = input_data.get('progress_interval')  # 可选，进度写入间隔
        
        if not file_paths:
            output_data = {
                "results": [],
                "stats": {"total": 0, "success": 0, "failed": 0, "elapsed_seconds": 0}
            }
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
        else:
            # 流式写入到 args.output，避免百万级时内存与一次性 dump 开销
            extract_metadata_parallel(
                file_paths=file_paths,
                num_workers=args.workers,
                progress_file=progress_file,
                max_workers_cap=max_workers,
                progress_interval=progress_interval,
                output_path=args.output,
            )
        
        sys.exit(0)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        
        # 尝试写入错误信息到输出文件
        try:
            error_data = {
                "error": str(e),
                "results": [],
                "stats": {
                    "total": 0,
                    "success": 0,
                    "failed": 0,
                    "elapsed_seconds": 0
                }
            }
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(error_data, f, ensure_ascii=False)
        except Exception:
            pass
        
        sys.exit(1)


if __name__ == '__main__':
    # Windows 下多进程必须的保护
    from multiprocessing import freeze_support
    freeze_support()
    
    main()
