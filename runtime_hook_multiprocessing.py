
import sys
import multiprocessing

# 强制使用 spawn 模式（Windows 默认，但显式设置更安全）
if sys.platform == 'win32':
    multiprocessing.set_start_method('spawn', force=True)
