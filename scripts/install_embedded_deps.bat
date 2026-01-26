@echo off
chcp 65001 >nul
REM ============================================================
REM Transcriptionist v3 - 内嵌依赖安装脚本
REM 
REM 此脚本将所有Python依赖安装到内嵌的runtime/python中
REM 使应用程序可以独立运行，无需系统Python
REM ============================================================

setlocal EnableDelayedExpansion

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║     音译家 Transcriptionist v3 - 内嵌依赖安装             ║
echo ╠════════════════════════════════════════════════════════════╣
echo ║  此脚本将安装所有依赖到内嵌Python运行时                   ║
echo ║  包括: GTK4/PyGObject + 所有Python库                      ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

REM 设置路径
set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "RUNTIME_DIR=%PROJECT_DIR%\runtime"
set "PYTHON_DIR=%RUNTIME_DIR%\python"
set "PYTHON_EXE=%PYTHON_DIR%\python.exe"
set "PIP_EXE=%PYTHON_DIR%\Scripts\pip.exe"
set "WHEELS_DIR=%RUNTIME_DIR%\wheels"
set "GTK4_DIR=%RUNTIME_DIR%\gtk4"

REM 检查内嵌Python是否存在
if not exist "%PYTHON_EXE%" (
    echo [错误] 未找到内嵌Python: %PYTHON_EXE%
    echo 请先运行 setup_runtime.bat 设置运行时环境
    pause
    exit /b 1
)

echo [信息] 使用内嵌Python: %PYTHON_EXE%
"%PYTHON_EXE%" --version

REM 确保pip已安装
echo.
echo [1/6] 检查并安装pip...
if not exist "%PIP_EXE%" (
    echo 正在安装pip...
    "%PYTHON_EXE%" "%RUNTIME_DIR%\get-pip.py" --no-warn-script-location
    if errorlevel 1 (
        echo [错误] pip安装失败
        pause
        exit /b 1
    )
)
echo pip已就绪

REM 升级pip
echo.
echo [2/6] 升级pip到最新版本...
"%PYTHON_EXE%" -m pip install --upgrade pip --no-warn-script-location -q

REM 创建wheels缓存目录
if not exist "%WHEELS_DIR%" mkdir "%WHEELS_DIR%"

REM 安装核心依赖
echo.
echo [3/6] 安装数据库依赖...
"%PYTHON_EXE%" -m pip install SQLAlchemy>=2.0.0 alembic>=1.12.0 --no-warn-script-location -q
if errorlevel 1 (
    echo [警告] 数据库依赖安装可能有问题
)
echo     √ SQLAlchemy, alembic

echo.
echo [4/6] 安装音频处理依赖...
"%PYTHON_EXE%" -m pip install mutagen>=1.47.0 soundfile>=0.12.0 pygame>=2.5.0 pyloudnorm>=0.1.1 --no-warn-script-location -q
if errorlevel 1 (
    echo [警告] 音频依赖安装可能有问题
)
echo     √ mutagen, soundfile, pygame, pyloudnorm

REM librosa和numpy需要特殊处理（较大）
echo.
echo [5/6] 安装AI/分析依赖（这可能需要几分钟）...
"%PYTHON_EXE%" -m pip install numpy>=1.24.0 --no-warn-script-location -q
echo     √ numpy
"%PYTHON_EXE%" -m pip install scikit-learn>=1.3.0 --no-warn-script-location -q
echo     √ scikit-learn
"%PYTHON_EXE%" -m pip install librosa>=0.10.0 --no-warn-script-location -q
echo     √ librosa

echo.
echo [6/6] 安装工具库依赖...
"%PYTHON_EXE%" -m pip install aiohttp>=3.9.0 aiofiles>=23.0.0 watchdog>=3.0.0 pydantic>=2.0.0 pydantic-settings>=2.0.0 --no-warn-script-location -q
if errorlevel 1 (
    echo [警告] 工具库依赖安装可能有问题
)
echo     √ aiohttp, aiofiles, watchdog, pydantic

REM 安装GTK4 Python绑定
echo.
echo [额外] 安装GTK4 Python绑定...
if exist "%GTK4_DIR%\python\pycairo-*.whl" (
    for %%f in ("%GTK4_DIR%\python\pycairo-*.whl") do (
        "%PYTHON_EXE%" -m pip install "%%f" --no-warn-script-location -q
    )
    echo     √ pycairo
)
if exist "%GTK4_DIR%\python\pygobject-*.whl" (
    for %%f in ("%GTK4_DIR%\python\pygobject-*.whl") do (
        "%PYTHON_EXE%" -m pip install "%%f" --no-warn-script-location -q
    )
    echo     √ pygobject
)

REM 验证安装
echo.
echo ════════════════════════════════════════════════════════════
echo 验证已安装的依赖...
echo ════════════════════════════════════════════════════════════
"%PYTHON_EXE%" -c "import sqlalchemy; print(f'  SQLAlchemy: {sqlalchemy.__version__}')"
"%PYTHON_EXE%" -c "import alembic; print(f'  Alembic: {alembic.__version__}')"
"%PYTHON_EXE%" -c "import mutagen; print(f'  Mutagen: {mutagen.version_string}')"
"%PYTHON_EXE%" -c "import soundfile; print(f'  SoundFile: {soundfile.__version__}')"
"%PYTHON_EXE%" -c "import pygame; print(f'  Pygame: {pygame.__version__}')"
"%PYTHON_EXE%" -c "import numpy; print(f'  NumPy: {numpy.__version__}')"
"%PYTHON_EXE%" -c "import sklearn; print(f'  Scikit-learn: {sklearn.__version__}')"
"%PYTHON_EXE%" -c "import aiohttp; print(f'  Aiohttp: {aiohttp.__version__}')"
"%PYTHON_EXE%" -c "import watchdog; print(f'  Watchdog: {watchdog.__version__}')"
"%PYTHON_EXE%" -c "import pydantic; print(f'  Pydantic: {pydantic.__version__}')"
"%PYTHON_EXE%" -c "import pycairo; print(f'  PyCairo: {pycairo.__version__}')"
"%PYTHON_EXE%" -c "import gi; print(f'  PyGObject: OK')"

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║                    安装完成！                              ║
echo ╠════════════════════════════════════════════════════════════╣
echo ║  所有依赖已安装到: runtime\python\Lib\site-packages       ║
echo ║                                                            ║
echo ║  运行应用: run.bat                                         ║
echo ╚════════════════════════════════════════════════════════════╝
echo.
pause
