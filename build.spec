# -*- mode: python ; coding: utf-8 -*-
"""
音译家 v1.1.0 - PyInstaller 打包配置文件

使用方法:
    pyinstaller build.spec

输出目录:
    dist/音译家 AI音效管理工具1.1.0/

本次打包要点:
- CLAP 音频预处理：preprocess_audio.onnx + preprocess_audio.onnx.data（两个文件）随包分发到 data/models/onnx_preprocess/（冻结时从 _MEIPASS 解析），DirectML GPU 加速，无则回退 NumPy
- 推理：ONNX Runtime + DirectML（model.onnx 统一双编码器模型，用户软件内下载）
- 多进程索引：runtime_hook + spawn，单文件预处理超时跳过
- 翻译：走「设置 -> AI 服务商配置」与「AI 批量翻译性能」；标签/批量翻译使用 translation_manager + openai_compatible（含本地模型 Ollama/LM Studio）；可选 HY-MT1.5 ONNX；内置 UCS/AudioSet 标签集
"""

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

# 项目根目录（即包含 __main__.py 的目录，包名 transcriptionist_v3 的物理文件夹）
project_root = Path('.').absolute()
# 父目录加入 pathex，使 Analysis 阶段能解析 from transcriptionist_v3.xxx（包在父目录下名为 transcriptionist_v3）
parent_root = project_root.parent
print(f"项目根目录: {project_root}")
print(f"父目录(pathex): {parent_root}")

# CLAP 预处理 ONNX（独立目录，避免「删除 CLAP 模型」时被清空）
_preprocess_dir = project_root / "data" / "models" / "onnx_preprocess"
# 检查并收集所有预处理 ONNX 文件（包括 .onnx 和 .onnx.data）
_preprocess_files = []
if _preprocess_dir.exists():
    for file_path in _preprocess_dir.iterdir():
        if file_path.is_file() and (file_path.suffix == '.onnx' or file_path.name.endswith('.onnx.data')):
            _preprocess_files.append(file_path.name)
if not _preprocess_files:
    raise SystemExit(
        "打包前请先运行: py scripts/export_clap_preprocess_onnx.py\n"
        f"缺失预处理文件，目录: {_preprocess_dir}"
    )
print(f"找到预处理文件: {_preprocess_files}")

# ============================================================
# 数据文件收集
# ============================================================
# 明确不打包（敏感/用户数据，运行时自动创建或用户自行配置）:
#   - data/           数据库、AI 索引、缓存、日志等
#   - data/models/    大模型（model.onnx 等）用户软件内下载
#   - data/models/larger-clap-general/  CLAP 大模型目录（model.onnx 约 800MB+），明确排除，用户软件内下载
#   - data/models/clap-htsat-unfused/   旧版 CLAP 模型目录，明确排除
#   - data/models/hy-mt1.5-onnx/       翻译模型目录，明确排除
#   - data/database/  音效库数据库 (*.db)
#   - config/        本地配置（含 API Key 等），不打包避免泄露
# 例外：预处理模型（所有 .onnx 和 .onnx.data 文件）随包分发以启用 CLAP 预处理 DirectML 加速（独立于 CLAP 模型目录，删除 CLAP 模型时不会被清空）。
# 打包前需运行: py scripts/export_clap_preprocess_onnx.py；导出后应存在预处理文件。
# AI 打标内置标签集（影视音效 753、AudioSet 等）在 ui/utils/*.py 中，由 hiddenimports 打包，无需额外 datas。
#
# ⚠️ 重要：PyInstaller 只会打包 datas 列表中明确指定的文件/目录，不会自动打包项目目录下的所有文件。
# 因此，只要不在 datas 中添加 data/models/larger-clap-general 等目录，CLAP 大模型就不会被打包。
# 自动收集所有预处理文件
_preprocess_datas = []
for file_name in _preprocess_files:
    _preprocess_datas.append((f'data/models/onnx_preprocess/{file_name}', 'data/models/onnx_preprocess'))
datas = [
    # UI 资源文件（路径必须与 ui/utils/resources.py 中 get_resource_path 一致，打包后为 _MEIPASS/ui/resources/...）
    ('ui/resources/icons', 'ui/resources/icons'),   # 应用图标 app_icon.png / app_icon.ico 等
    ('ui/resources/images', 'ui/resources/images'),  # 帮助与反馈-联系我 微信二维码 wechat_qr.png
    ('ui/resources/styles', 'ui/resources/styles'),
    
    # 字体文件 (HarmonyOS Sans)
    ('resources/fonts', 'resources/fonts'),
    
    # 国际化翻译文件
    ('locale', 'locale'),
    
    # 许可证和文档（不含任何密钥）
    ('LICENSE', '.'),
    ('COPYING', '.'),
    ('README.md', '.'),
    ('GPL_COMPLIANCE_CHECKLIST.md', '.'),
    
    # CLAP 预处理 ONNX（波形→Mel，两个文件：preprocess_audio.onnx + preprocess_audio.onnx.data，独立目录，删除 CLAP 模型时不会被清空）
] + _preprocess_datas

# ============================================================
# 隐藏导入（确保所有模块都被打包）
# ============================================================
# 1) 不使用 collect_submodules('transcriptionist_v3')
# 原因：collect_submodules 在部分环境会触发导入副作用，导致类似
#   - ModuleNotFoundError: No module named 'gi'（GStreamer）
# 的警告/失败，增加“不确定性”。
# 这里改为：只显式列出我们确实需要的 hiddenimports + 对第三方包用 collect_all()。
project_hidden_imports: list[str] = []

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
    
    # === 数据库（包名小写 sqlalchemy，否则 PyInstaller 报 Hidden import not found）===
    'sqlalchemy',
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
    
    # === Numba (Librosa JIT 编译依赖) ===
    'numba',
    'numba.core',
    'numba.core.types',
    'numba.core.typing',
    'numba.core.bytecode',
    'numba.core.interpreter',
    
    # === ONNX Runtime ===
    'onnxruntime',
    'onnxruntime.capi',
    'onnxruntime.capi.onnxruntime_pybind11_state',
    
    # === CLAP 官方对齐预处理（无 PyTorch/transformers）===
    'transcriptionist_v3.application.ai.clap_preprocess',
    
    # === 翻译：统一配置 + OpenAI 兼容（标签/批量翻译、Ollama/LM Studio）===
    'transcriptionist_v3.application.ai_engine.translation_manager',
    'transcriptionist_v3.application.ai_engine.service_factory',
    'transcriptionist_v3.application.ai_engine.provider_registry',
    'transcriptionist_v3.application.ai_engine.providers.openai_compatible',
    'transcriptionist_v3.application.ai_engine.providers.deepseek',
    'transcriptionist_v3.application.ai_engine.translation_cache',
    'transcriptionist_v3.application.ai_engine.providers.hy_mt15_onnx',
    
    # === AI 任务（打标/索引任务、选择与作业存储）===
    'transcriptionist_v3.application.ai_jobs.selection',
    'transcriptionist_v3.application.ai_jobs.job_store',
    'transcriptionist_v3.application.ai_jobs.job_constants',
    'transcriptionist_v3.application.ai_jobs.index_writer',
    
    # === packaging ===
    # packaging 子模块在不同版本/平台可能变化；这里不硬编码内部子模块，避免 “Hidden import not found!” 噪声。
    # 依赖收集由下面的 collect_all('packaging') 负责。
    'packaging',
    # === 工具库 ===
    'watchdog',
    'watchdog.observers',
    'pydantic',
    'pydantic_settings',
    'psutil',           # 内存/物理核检测（块大小、CPU 并行数等设备推荐）
    
    # === 国际化 ===
    'gettext',
    'locale',
    
    # === AI 打标内置标签集（务必打包）===
    'transcriptionist_v3.ui.utils.ucs_labels_data',   # 影视音效(753) UCS v8.2.1 内置
    'transcriptionist_v3.ui.utils.audioset_labels',    # 音效精简(70+)、全量 AudioSet(527)
    
    # === 多进程支持（CRITICAL for Windows multiprocessing in frozen exe）===
    'multiprocessing',
    'multiprocessing.spawn',
    'multiprocessing.pool',
    'multiprocessing.managers',
    'multiprocessing.queues',
    'multiprocessing.synchronize',
    'multiprocessing.connection',
    'multiprocessing.context',
    'multiprocessing.popen_spawn_win32',
] + project_hidden_imports

# ============================================================
# 强制收集依赖包 (Fix missing modules)
# ============================================================
packages_to_collect = [
    # 只收集“确实经常缺失且 PyInstaller 不一定自动收齐”的包。
    # 过度 collect_all() 会引入平台/可选依赖扫描（例如 torch/gi/onnx）从而产生噪声警告甚至失败。
    'packaging',       # Fix: 部分环境缺 packaging 子模块
    'tokenizers',      # Fix: CLAP 文本编码
    'librosa',         # Fix: 音频加载与特征提取
    'numba',           # Fix: librosa JIT 加速依赖（若启用）
    'soundfile',       # Fix: 音频文件读写
    'pyloudnorm',      # Fix: 响度标准化
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
# Intel TBB DLL 收集 (numba 并行加速依赖)
# ============================================================
# tbb12.dll 等 TBB 库位于 runtime/python/Library/bin/ 目录
# 这些是 numba tbbpool 的运行时依赖
_tbb_dir = project_root / "runtime" / "python" / "Library" / "bin"
_tbb_dlls = ['tbb12.dll', 'tbbmalloc.dll', 'tbbmalloc_proxy.dll', 
             'tbbbind.dll', 'tbbbind_2_0.dll', 'tbbbind_2_5.dll']
_tbb_collected = 0
for dll_name in _tbb_dlls:
    dll_path = _tbb_dir / dll_name
    if dll_path.exists():
        binaries.append((str(dll_path), '.'))
        _tbb_collected += 1
if _tbb_collected > 0:
    print(f"Collected TBB: {_tbb_collected} DLLs from {_tbb_dir}")
else:
    print(f"Warning: No TBB DLLs found in {_tbb_dir} - numba parallel features may be limited")

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
    
    # AI 框架（体积大，仅用 ONNX 推理 + 官方对齐 NumPy 预处理）
    'torch',          # CLAP 预处理已用 clap_preprocess（preprocessor_config.json），无需 PyTorch
    'tensorflow',
    'transformers',   # 不再使用 ClapProcessor，避免误拉入
]

# ============================================================
# 多进程支持（重要！）
# ============================================================
# PyInstaller 打包后，multiprocessing 需要特殊处理：
# 1. 本 spec：multiprocessing_freeze_support、hiddenimports、runtime_hook
# 2. __main__.py：入口处 freeze_support() + 子进程守卫（-c 时 exec 代码并退出，避免子进程再跑 GUI）
import PyInstaller.config
PyInstaller.config.CONF['multiprocessing_freeze_support'] = True

# 创建运行时钩子文件（确保子进程能正确启动）
runtime_hook_content = """
import sys
import multiprocessing

# 强制使用 spawn 模式（Windows 默认，但显式设置更安全）
if sys.platform == 'win32':
    multiprocessing.set_start_method('spawn', force=True)
"""

runtime_hook_path = project_root / 'runtime_hook_multiprocessing.py'
with open(runtime_hook_path, 'w', encoding='utf-8') as f:
    f.write(runtime_hook_content)

print(f"Created runtime hook: {runtime_hook_path}")

# ============================================================
# 分析阶段
# ============================================================
block_cipher = None

a = Analysis(
    ['__main__.py'],
    pathex=[str(project_root), str(parent_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(project_root)],
    hooksconfig={},
    runtime_hooks=[str(runtime_hook_path)],  # 添加多进程运行时钩子
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

# 主程序 exe 图标（必须与 datas 中 ui/resources/icons 一致，打包后任务栏/窗口图标由此提供）
icon_path = project_root / 'ui' / 'resources' / 'icons' / 'app_icon.ico'
icon_file = str(icon_path) if icon_path.exists() else None
if icon_file:
    print(f"使用图标文件: {icon_path}")
else:
    print("警告: 未找到 app_icon.ico，将使用默认图标。请确保 ui/resources/icons/app_icon.ico 存在（可由 convert_icon.py 生成）")

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='音译家 AI音效管理工具1.1.0',
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
# metadata_worker.py 独立后台进程
# ============================================================
# 为 metadata_worker.py 创建单独的分析对象（重用依赖配置）
a_worker = Analysis(
    ['scripts/metadata_worker.py'],
    pathex=[str(project_root), str(parent_root)],
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

metadata_worker_pyz = PYZ(a_worker.pure, a_worker.zipped_data, cipher=block_cipher)

metadata_worker_exe = EXE(
    metadata_worker_pyz,
    a_worker.scripts,
    [],
    exclude_binaries=True,
    name='metadata_worker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # 显示控制台窗口（后台进程需要输出）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ============================================================
# 收集所有文件到目录
# ============================================================
# 合并两个程序的依赖（自动去重）
all_binaries = a.binaries + a_worker.binaries
all_zipfiles = a.zipfiles + a_worker.zipfiles
all_datas = a.datas + a_worker.datas

coll = COLLECT(
    exe,
    metadata_worker_exe,  # 包含 metadata_worker 可执行文件
    all_binaries,
    all_zipfiles,
    all_datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='音译家 AI音效管理工具1.1.0',  # 绿色版输出文件夹及主程序名
)

print("=" * 60)
print("打包配置完成！")
print("=" * 60)
print(f"输出目录: {project_root / 'dist' / '音译家 AI音效管理工具1.1.0'}")
print("包含的可执行文件:")
print("  - 音译家 AI音效管理工具1.1.0.exe (主程序)")
print("  - metadata_worker.exe (元数据提取后台进程)")
print("=" * 60)
