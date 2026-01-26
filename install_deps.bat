@echo off
chcp 65001 >nul
REM ============================================================
REM Transcriptionist v3 - 依赖安装入口
REM 
REM 此脚本会调用内嵌依赖安装脚本
REM ============================================================

setlocal EnableDelayedExpansion

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║     音译家 Transcriptionist v3 - 依赖安装                 ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

set "SCRIPT_DIR=%~dp0"

REM 检查是否有内嵌Python
if exist "%SCRIPT_DIR%runtime\python\python.exe" (
    echo [检测到内嵌Python运行时]
    echo 将安装依赖到内嵌环境...
    echo.
    call "%SCRIPT_DIR%scripts\install_embedded_deps.bat"
) else (
    echo [未检测到内嵌Python运行时]
    echo 将使用系统Python安装依赖...
    echo.
    
    REM 检查系统Python
    python --version >nul 2>&1
    if errorlevel 1 (
        echo 错误: 未找到 Python，请先安装 Python 3.10+
        pause
        exit /b 1
    )
    
    echo 正在安装依赖...
    pip install -r "%SCRIPT_DIR%requirements.txt"
    
    echo.
    echo 安装完成！
)

endlocal
