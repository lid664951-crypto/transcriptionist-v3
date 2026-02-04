"""
Core utility functions for transcriptionist_v3.
Provides common formatting and helper functions used across the application.
"""

import sys
from typing import Union


def _validate_ram_gb(value: float) -> bool:
    """内存 GB 合理性：大于 0 且不超过 2048（2TB）"""
    return 0 < value <= 2048.0


def get_system_ram_gb() -> float:
    """
    获取系统物理内存总量（GB），用于根据内存决定默认块大小等。
    多方式检测，避免打包/32 位环境或结构体错误导致显示为 8GB。
    
    Returns:
        内存总量（GB），检测失败时返回 8.0 作为保守默认值。
    """
    # 1. psutil（开发/打包后若已包含则优先）
    try:
        import psutil
        total_bytes = psutil.virtual_memory().total
        gb = total_bytes / (1024 ** 3)
        if _validate_ram_gb(gb):
            return gb
    except ImportError:
        pass
    except Exception:
        pass

    # 2. Windows：GetPhysicallyInstalledSystemMemory（返回 KB，Vista+，读 SMBIOS 较准）
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            total_kb = ctypes.c_ulonglong(0)
            if kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(total_kb)):
                gb = total_kb.value / (1024 * 1024)
                if _validate_ram_gb(gb):
                    return gb
        except (AttributeError, Exception):
            pass

        # 3. Windows：GlobalMemoryStatusEx（DWORD 必须 32 位，否则 64 位 Python 下结构错位会得到错误值）
        try:
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_uint32),
                    ("dwMemoryLoad", ctypes.c_uint32),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                ]
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            m = MEMORYSTATUSEX()
            m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                gb = m.ullTotalPhys / (1024 ** 3)
                if _validate_ram_gb(gb):
                    return gb
        except Exception:
            pass

        # 4. Windows：wmic 备用
        try:
            import subprocess
            r = subprocess.run(
                ["wmic", "computersystem", "get", "TotalPhysicalMemory", "/value"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0 and r.stdout:
                for line in r.stdout.strip().splitlines():
                    if "=" in line:
                        key, _, val = line.partition("=")
                        if key.strip().lower() == "totalphysicalmemory":
                            total_bytes = int(val.strip())
                            gb = total_bytes / (1024 ** 3)
                            if _validate_ram_gb(gb):
                                return gb
                            break
        except (FileNotFoundError, ValueError, Exception):
            pass

    return 8.0


def get_physical_cpu_count() -> int | None:
    """
    获取物理 CPU 核心数（不含超线程），用于根据真实核心数推荐并行数。
    
    Returns:
        物理核心数，检测失败或不可用时返回 None（调用方可用逻辑核心数代替）。
    """
    try:
        import psutil
        return psutil.cpu_count(logical=False)
    except (ImportError, AttributeError, Exception):
        return None


def format_file_size(size: int) -> str:
    """
    Format a file size in bytes to a human-readable string.
    
    Args:
        size: File size in bytes
        
    Returns:
        Formatted string like "1.5 MB", "256 KB", or "512 B"
    """
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"


def format_duration(seconds: Union[int, float]) -> str:
    """
    Format a duration in seconds to MM:SS or HH:MM:SS format.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted string like "03:45" or "1:23:45"
    """
    if seconds < 0:
        return "-"
    
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"


def format_sample_rate(sample_rate: int) -> str:
    """
    Format a sample rate to a human-readable string.
    
    Args:
        sample_rate: Sample rate in Hz
        
    Returns:
        Formatted string like "48.0k" or "44.1k"
    """
    if sample_rate <= 0:
        return "-"
    return f"{sample_rate / 1000:.1f}k"


def format_channels(channels: int) -> str:
    """
    Format audio channel count to a human-readable string.
    
    Args:
        channels: Number of audio channels
        
    Returns:
        Formatted string like "单声道", "立体声", or "5.1 声道"
    """
    if channels == 1:
        return "单声道"
    elif channels == 2:
        return "立体声"
    elif channels > 0:
        return f"{channels} 声道"
    else:
        return "-"


def format_bit_depth(bit_depth: int) -> str:
    """
    Format bit depth to a human-readable string.
    
    Args:
        bit_depth: Bit depth (e.g., 16, 24, 32)
        
    Returns:
        Formatted string like "24 bit"
    """
    if bit_depth > 0:
        return f"{bit_depth} bit"
    else:
        return "-"
