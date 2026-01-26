#!/usr/bin/env python3
"""
Transcriptionist v3 - 内嵌依赖安装脚本 (Python版本)

此脚本将所有Python依赖安装到内嵌的runtime/python中，
使应用程序可以独立运行，无需系统Python。

用法:
    python scripts/install_embedded_deps.py [--dev] [--force]
    
参数:
    --dev    安装开发依赖（测试、代码检查等）
    --force  强制重新安装所有依赖
"""

import subprocess
import sys
import os
from pathlib import Path
from typing import List, Tuple

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
RUNTIME_DIR = PROJECT_ROOT / "runtime"
PYTHON_DIR = RUNTIME_DIR / "python"
PYTHON_EXE = PYTHON_DIR / "python.exe"
WHEELS_DIR = RUNTIME_DIR / "wheels"

# 核心依赖列表
CORE_DEPENDENCIES: List[Tuple[str, str, str]] = [
    # (包名, 版本要求, 描述)
    # 数据库
    ("SQLAlchemy", ">=2.0.0", "ORM框架"),
    ("alembic", ">=1.12.0", "数据库迁移"),
    
    # 音频处理
    ("mutagen", ">=1.47.0", "音频元数据"),
    ("soundfile", ">=0.12.0", "音频文件读写"),
    ("pygame", ">=2.5.0", "音频播放"),
    ("pyloudnorm", ">=0.1.1", "响度标准化"),
    
    # AI/分析
    ("numpy", ">=1.24.0", "数值计算"),
    ("scikit-learn", ">=1.3.0", "机器学习"),
    ("librosa", ">=0.10.0", "音频分析"),
    
    # 网络/异步
    ("aiohttp", ">=3.9.0", "异步HTTP"),
    ("aiofiles", ">=23.0.0", "异步文件"),
    
    # 工具库
    ("watchdog", ">=3.0.0", "文件监控"),
    ("pydantic", ">=2.0.0", "数据验证"),
    ("pydantic-settings", ">=2.0.0", "配置管理"),
]

# 开发依赖
DEV_DEPENDENCIES: List[Tuple[str, str, str]] = [
    ("pytest", ">=7.4.0", "测试框架"),
    ("pytest-asyncio", ">=0.21.0", "异步测试"),
    ("pytest-cov", ">=4.1.0", "覆盖率"),
    ("pytest-mock", ">=3.11.0", "Mock支持"),
    ("hypothesis", ">=6.82.0", "属性测试"),
    ("black", ">=23.7.0", "代码格式化"),
    ("isort", ">=5.12.0", "导入排序"),
    ("ruff", ">=0.1.0", "代码检查"),
    ("mypy", ">=1.5.0", "类型检查"),
]


def print_header():
    """打印标题"""
    print()
    print("╔" + "═" * 60 + "╗")
    print("║" + "音译家 Transcriptionist v3 - 内嵌依赖安装".center(52) + "║")
    print("╠" + "═" * 60 + "╣")
    print("║" + "此脚本将安装所有依赖到内嵌Python运行时".center(52) + "║")
    print("╚" + "═" * 60 + "╝")
    print()


def check_embedded_python() -> bool:
    """检查内嵌Python是否存在"""
    if not PYTHON_EXE.exists():
        print(f"[错误] 未找到内嵌Python: {PYTHON_EXE}")
        print("请先运行 setup_runtime.bat 设置运行时环境")
        return False
    
    # 获取Python版本
    result = subprocess.run(
        [str(PYTHON_EXE), "--version"],
        capture_output=True,
        text=True
    )
    print(f"[信息] 使用内嵌Python: {result.stdout.strip()}")
    return True


def ensure_pip():
    """确保pip已安装"""
    print("\n[1/6] 检查并安装pip...")
    
    pip_exe = PYTHON_DIR / "Scripts" / "pip.exe"
    if not pip_exe.exists():
        print("正在安装pip...")
        get_pip = RUNTIME_DIR / "get-pip.py"
        if get_pip.exists():
            subprocess.run(
                [str(PYTHON_EXE), str(get_pip), "--no-warn-script-location"],
                check=True
            )
        else:
            # 下载get-pip.py
            import urllib.request
            url = "https://bootstrap.pypa.io/get-pip.py"
            urllib.request.urlretrieve(url, str(get_pip))
            subprocess.run(
                [str(PYTHON_EXE), str(get_pip), "--no-warn-script-location"],
                check=True
            )
    
    # 升级pip
    print("\n[2/6] 升级pip到最新版本...")
    subprocess.run(
        [str(PYTHON_EXE), "-m", "pip", "install", "--upgrade", "pip", 
         "--no-warn-script-location", "-q"],
        check=True
    )
    print("pip已就绪")


def install_package(name: str, version: str, description: str, force: bool = False) -> bool:
    """安装单个包"""
    package_spec = f"{name}{version}"
    args = [
        str(PYTHON_EXE), "-m", "pip", "install",
        package_spec,
        "--no-warn-script-location",
        "-q"
    ]
    if force:
        args.append("--force-reinstall")
    
    try:
        subprocess.run(args, check=True, capture_output=True)
        print(f"    √ {name} ({description})")
        return True
    except subprocess.CalledProcessError as e:
        print(f"    × {name} - 安装失败: {e.stderr.decode() if e.stderr else '未知错误'}")
        return False


def install_dependencies(deps: List[Tuple[str, str, str]], 
                         category: str, 
                         step: str,
                         force: bool = False):
    """安装一组依赖"""
    print(f"\n[{step}] 安装{category}...")
    
    success_count = 0
    for name, version, desc in deps:
        if install_package(name, version, desc, force):
            success_count += 1
    
    print(f"    已安装 {success_count}/{len(deps)} 个包")


def verify_installation():
    """验证安装"""
    print("\n" + "═" * 60)
    print("验证已安装的依赖...")
    print("═" * 60)
    
    packages_to_check = [
        ("sqlalchemy", "SQLAlchemy"),
        ("alembic", "Alembic"),
        ("mutagen", "Mutagen"),
        ("soundfile", "SoundFile"),
        ("pygame", "Pygame"),
        ("numpy", "NumPy"),
        ("sklearn", "Scikit-learn"),
        ("aiohttp", "Aiohttp"),
        ("watchdog", "Watchdog"),
        ("pydantic", "Pydantic"),
    ]
    
    for module, display_name in packages_to_check:
        try:
            result = subprocess.run(
                [str(PYTHON_EXE), "-c", 
                 f"import {module}; print(getattr({module}, '__version__', getattr({module}, 'version_string', 'OK')))"],
                capture_output=True,
                text=True
            )
            version = result.stdout.strip()
            print(f"  {display_name}: {version}")
        except Exception:
            print(f"  {display_name}: 未安装")


def print_footer():
    """打印结束信息"""
    print()
    print("╔" + "═" * 60 + "╗")
    print("║" + "安装完成！".center(56) + "║")
    print("╠" + "═" * 60 + "╣")
    print("║  所有依赖已安装到: runtime\\python\\Lib\\site-packages" + " " * 5 + "║")
    print("║" + " " * 60 + "║")
    print("║  运行应用: run.bat" + " " * 41 + "║")
    print("╚" + "═" * 60 + "╝")
    print()


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="安装Transcriptionist v3依赖")
    parser.add_argument("--dev", action="store_true", help="安装开发依赖")
    parser.add_argument("--force", action="store_true", help="强制重新安装")
    args = parser.parse_args()
    
    print_header()
    
    if not check_embedded_python():
        sys.exit(1)
    
    ensure_pip()
    
    # 创建wheels缓存目录
    WHEELS_DIR.mkdir(exist_ok=True)
    
    # 分组安装依赖
    db_deps = [d for d in CORE_DEPENDENCIES if d[0] in ("SQLAlchemy", "alembic")]
    audio_deps = [d for d in CORE_DEPENDENCIES if d[0] in ("mutagen", "soundfile", "pygame", "pyloudnorm")]
    ai_deps = [d for d in CORE_DEPENDENCIES if d[0] in ("numpy", "scikit-learn", "librosa")]
    util_deps = [d for d in CORE_DEPENDENCIES if d[0] in ("aiohttp", "aiofiles", "watchdog", "pydantic", "pydantic-settings")]
    
    install_dependencies(db_deps, "数据库依赖", "3/6", args.force)
    install_dependencies(audio_deps, "音频处理依赖", "4/6", args.force)
    
    print("\n[5/6] 安装AI/分析依赖（这可能需要几分钟）...")
    for name, version, desc in ai_deps:
        install_package(name, version, desc, args.force)
    
    install_dependencies(util_deps, "工具库依赖", "6/6", args.force)
    
    if args.dev:
        print("\n[额外] 安装开发依赖...")
        for name, version, desc in DEV_DEPENDENCIES:
            install_package(name, version, desc, args.force)
    
    verify_installation()
    print_footer()


if __name__ == "__main__":
    main()
