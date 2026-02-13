# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_all
import PyInstaller.config

project_root = Path('.').absolute()
parent_root = project_root.parent
app_basename = "音译家AI音效管理工具1.2.0"

print(f"Project root: {project_root}")
print(f"Parent root for pathex: {parent_root}")

# -----------------------------------------------------------------
# Required preprocess model files
# -----------------------------------------------------------------
preprocess_dir = project_root / "data" / "models" / "onnx_preprocess"
preprocess_files = []
if preprocess_dir.exists():
    for file_path in preprocess_dir.iterdir():
        if file_path.is_file() and (file_path.suffix == ".onnx" or file_path.name.endswith(".onnx.data")):
            preprocess_files.append(file_path.name)

if not preprocess_files:
    raise SystemExit(
        "Missing ONNX preprocess files under data/models/onnx_preprocess. "
        "Run scripts/export_clap_preprocess_onnx.py first."
    )

print(f"Found preprocess files: {preprocess_files}")

# -----------------------------------------------------------------
# Data files to include (icons/images/resources/locales/plugins)
# -----------------------------------------------------------------
preprocess_datas = [
    (f"data/models/onnx_preprocess/{name}", "data/models/onnx_preprocess")
    for name in preprocess_files
]

datas = [
    ("ui/resources/icons", "ui/resources/icons"),
    ("ui/resources/images", "ui/resources/images"),
    ("ui/resources/styles", "ui/resources/styles"),
    ("resources/fonts", "resources/fonts"),
    ("locale", "locale"),
    ("plugins", "plugins"),
] + preprocess_datas

# -----------------------------------------------------------------
# Hidden imports
# -----------------------------------------------------------------
hiddenimports = [
    "transcriptionist_v3.application.ai_engine.translation_manager",
    "transcriptionist_v3.application.ai_engine.service_factory",
    "transcriptionist_v3.application.ai_engine.provider_registry",
    "transcriptionist_v3.application.ai_engine.providers.openai_compatible",
    "transcriptionist_v3.application.ai_engine.providers.deepseek",
    "transcriptionist_v3.application.ai_engine.providers.kling_audio",
    "transcriptionist_v3.application.ai_engine.providers.hy_mt15_onnx",
    "transcriptionist_v3.ui.utils.ucs_labels_data",
    "transcriptionist_v3.ui.utils.audioset_labels",
    "multiprocessing",
    "multiprocessing.spawn",
    "multiprocessing.pool",
    "multiprocessing.managers",
    "multiprocessing.queues",
    "multiprocessing.synchronize",
    "multiprocessing.connection",
    "multiprocessing.context",
    "multiprocessing.popen_spawn_win32",
]

# Collect selected packages safely
packages_to_collect = [
    "packaging",
    "tokenizers",
    "librosa",
    "numba",
    "soundfile",
    "pyloudnorm",
]

binaries = []
for package in packages_to_collect:
    try:
        pkg_datas, pkg_bins, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_bins
        hiddenimports += pkg_hidden
        print(f"Collected {package}: datas={len(pkg_datas)} bins={len(pkg_bins)}")
    except Exception as exc:
        print(f"Warning: collect_all failed for {package}: {exc}")

# TBB DLLs for numba parallel runtime
tbb_dir = project_root / "runtime" / "python" / "Library" / "bin"
tbb_dlls = [
    "tbb12.dll",
    "tbbmalloc.dll",
    "tbbmalloc_proxy.dll",
    "tbbbind.dll",
    "tbbbind_2_0.dll",
    "tbbbind_2_5.dll",
]
for dll_name in tbb_dlls:
    dll_path = tbb_dir / dll_name
    if dll_path.exists():
        binaries.append((str(dll_path), "."))

excludes = [
    "tkinter",
    "PyQt5",
    "PyQt6",
    "wx",
    "pandas",
    "IPython",
    "jupyter",
    "notebook",
    "pytest",
    "sphinx",
    "black",
    "isort",
    "mypy",
    "torch",
    "tensorflow",
    "transformers",
]

# multiprocessing support for frozen build
PyInstaller.config.CONF["multiprocessing_freeze_support"] = True

runtime_hook_path = project_root / "runtime_hook_multiprocessing.py"
runtime_hook_path.write_text(
    "import sys\n"
    "import multiprocessing\n"
    "if sys.platform == 'win32':\n"
    "    multiprocessing.set_start_method('spawn', force=True)\n",
    encoding="utf-8",
)

block_cipher = None

a = Analysis(
    ["__main__.py"],
    pathex=[str(project_root), str(parent_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(project_root)],
    hooksconfig={},
    runtime_hooks=[str(runtime_hook_path)],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

icon_path = project_root / "ui" / "resources" / "icons" / "app_icon.ico"
icon_file = str(icon_path) if icon_path.exists() else None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_basename,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)

# metadata worker executable
a_worker = Analysis(
    ["scripts/metadata_worker.py"],
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
    name="metadata_worker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

all_binaries = a.binaries + a_worker.binaries
all_zipfiles = a.zipfiles + a_worker.zipfiles
all_datas = a.datas + a_worker.datas

coll = COLLECT(
    exe,
    metadata_worker_exe,
    all_binaries,
    all_zipfiles,
    all_datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=app_basename,
)

print("=" * 60)
print("PyInstaller spec ready")
print(f"Output directory: {project_root / 'dist' / app_basename}")
print("Executables:")
print(f"  - {app_basename}.exe")
print("  - metadata_worker.exe")
print("=" * 60)
