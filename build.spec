# -*- mode: python ; coding: utf-8 -*-
"""
音译家 v1.0.0 - PyInstaller 打包配置文件

使用方法:
    pyinstaller build.spec

输出目录:
    dist/音译家/
"""

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

# 项目根目录
project_root = Path('.').absolute()
print(f"项目根目录: {project_root}")

# ============================================================
# 数据文件收集
# ============================================================
datas = [
    # UI 资源文件
    ('ui/resources/icons', 'ui/resources/icons'),
    ('ui/resources/images', 'ui/resources/images'),
    ('ui/resources/styles', 'ui/resources/styles'),
    
    # 字体文件 (HarmonyOS Sans)
    ('resources/fonts', 'resources/fonts'),
    
    # 配置目录
    ('config', 'config'),
    
    # 许可证和文档
    ('LICENSE', '.'),
    ('COPYING', '.'),
    ('README.md', '.'),
    ('GPL_COMPLIANCE_CHECKLIST.md', '.'),
]

# 注意: data 目录不打包，让程序运行时自动创建
# 避免打包用户数据（数据库、模型文件等）

# ============================================================
# 隐藏导入（确保所有模块都被打包）
# ============================================================
# 1. 自动收集项目内的所有子模块
project_hidden_imports = collect_submodules('transcriptionist_v3')

hiddenimports = [
    # === PySide6 核心模块 ===
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtMultimedia',
    'PySide6.QtNetwork',
    
    # === qfluentwidgets ===
    'qfluentwidgets',
    'qfluentwidgets.components',
    'qfluentwidgets.components.widgets',
    'qfluentwidgets.components.dialog_box',
    'qfluentwidgets.components.settings',
    'qfluentwidgets.common',
    'qfluentwidgets.common.config',
    'qfluentwidgets.common.icon',
    'qfluentwidgets.common.style_sheet',
    'qfluentwidgets.window',
    'qframelesswindow',
    
    # === 数据库 ===
    'SQLAlchemy',
    'sqlalchemy.ext.declarative',
    'sqlalchemy.orm',
    'alembic',
    
    # === 音频处理 ===
    'mutagen',
    'soundfile',
    'pygame',
    'pygame.mixer',
    
    # === 网络 ===
    'aiohttp',
    'aiohttp.client',
    'aiohttp.web',
    'aiofiles',
    
    # === 数据处理 ===
    'numpy',
    'numpy.core',
    'numpy.core._multiarray_umath',
    
    # === 工具库 ===
    'watchdog',
    'watchdog.observers',
    'pydantic',
    'pydantic_settings',
] + project_hidden_imports

# ============================================================
# 强制收集依赖包 (Fix missing modules)
# ============================================================
packages_to_collect = [
    'packaging',       # Fix: No module named packaging.markers
    'tokenizers',      # Fix: AI functionality (MusicGen, CLAP)
    'librosa',         # Fix: AI Search audio processing
    'sklearn',         # Fix: Librosa dependency
    'scipy',           # Fix: Librosa hard dependency
    'onnxruntime',     # Fix: AI Inference
]

binaries = []
for package in packages_to_collect:
    try:
        tmp_ret = collect_all(package)
        datas += tmp_ret[0]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
        print(f"Collected {package}: {len(tmp_ret[0])} datas, {len(tmp_ret[1])} binaries")
    except Exception as e:
        print(f"Warning: Failed to collect {package}: {e}")

# ============================================================
# 排除模块（减小体积）
# ============================================================
excludes = [
    # GUI 框架（不需要的）
    'tkinter',
    'PyQt5',
    'PyQt6',
    'wx',
    
    # 科学计算（不需要的）
    # 'matplotlib', # 可选，如果使用了音频绘图需要保留
    'pandas',     
    
    # 开发工具
    'IPython',
    'jupyter',
    'notebook',
    'pytest',
    'sphinx',
    'black',
    'isort',
    'mypy',
    
    # AI 框架（体积大，让用户下载，只保留推理运行时）
    'torch',       # 我们使用 onnxruntime 进行推理，不需要 PyTorch
    'tensorflow',
]

# ============================================================
# 分析阶段
# ============================================================
block_cipher = None

a = Analysis(
    ['__main__.py'],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(project_root)],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ============================================================
# 打包阶段
# ============================================================
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ============================================================
# 可执行文件
# ============================================================

# 图标文件路径（使用绝对路径确保打包时能找到）
icon_path = project_root / 'ui' / 'resources' / 'icons' / 'app_icon.ico'
icon_file = str(icon_path) if icon_path.exists() else None

if icon_file:
    print(f"使用图标文件: {icon_file}")
else:
    print("警告: 未找到图标文件，将使用默认图标")

# ============================================================
# 多进程支持（重要！）
# ============================================================
# PyInstaller 打包后，multiprocessing 需要特殊处理
# 添加 multiprocessing 运行时钩子
import PyInstaller.config
PyInstaller.config.CONF['multiprocessing_freeze_support'] = True

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='音译家',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # 使用 UPX 压缩
    console=False,  # 不显示控制台窗口（GUI 应用）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)

# ============================================================
# 收集所有文件到目录
# ============================================================
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='音译家 AI 音效管理工具',  # 修改输出文件夹名称
)

print("=" * 60)
print("打包配置完成！")
print("=" * 60)
print(f"输出目录: {project_root / 'dist' / '音译家 AI 音效管理工具'}")
print("=" * 60)
