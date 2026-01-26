@echo off
setlocal EnableDelayedExpansion

REM Transcriptionist v3 Launcher
REM Uses embedded Python 3.13 and bundled GTK4 runtime (gvsbuild)

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Set up embedded Python
set "PYTHON_HOME=%SCRIPT_DIR%runtime\python"
set "PYTHON_EXE=%PYTHON_HOME%\python.exe"

REM ============================================================
REM GTK4 环境配置 - 使用本地打包的 GTK4 运行时
REM ============================================================
set "GTK4_HOME=%SCRIPT_DIR%runtime\gtk4"

REM 添加 GTK4 DLL 路径到 PATH（必须在最前面）
set "PATH=%GTK4_HOME%\bin;%PYTHON_HOME%;%PYTHON_HOME%\Scripts;%PATH%"

REM 设置 GObject Introspection typelib 路径
set "GI_TYPELIB_PATH=%GTK4_HOME%\lib\girepository-1.0"

REM 设置 GLib schemas 路径
set "GSETTINGS_SCHEMA_DIR=%GTK4_HOME%\share\glib-2.0\schemas"

REM 设置 GTK 数据路径
set "XDG_DATA_DIRS=%GTK4_HOME%\share"

REM 设置 PyGObject 路径
set "PYTHONPATH=%GTK4_HOME%\lib\site-packages;%SCRIPT_DIR%"

REM 强制使用 Cairo 渲染器避免 Windows 黑边问题
set "GSK_RENDERER=cairo"

REM Windows IME 支持
set "GTK_IM_MODULE=ime"

REM Check if Python exists
if not exist "%PYTHON_EXE%" (
    echo ERROR: Embedded Python not found at %PYTHON_EXE%
    echo Please ensure the runtime is properly installed.
    pause
    exit /b 1
)

REM Check if GTK4 exists
if not exist "%GTK4_HOME%\bin\gtk-4-1.dll" (
    echo ERROR: GTK4 runtime not found
    echo Please ensure the GTK4 runtime is properly installed in runtime\gtk4
    pause
    exit /b 1
)

REM Run the application
"%PYTHON_EXE%" -m transcriptionist_v3 %*

if errorlevel 1 (
    echo.
    echo Application exited with error code %errorlevel%
    pause
)

endlocal
