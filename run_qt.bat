@echo off
chcp 65001 >nul
title 音译家 Transcriptionist v3

cd /d "%~dp0"

echo ========================================
echo   音译家 Transcriptionist v3
echo   PySide6 + Fluent Widgets
echo ========================================
echo.

set PYTHON_EXE=runtime\python\python.exe

if not exist "%PYTHON_EXE%" (
    echo [错误] 未找到内嵌Python: %PYTHON_EXE%
    echo 请确保runtime\python目录存在
    pause
    exit /b 1
)

echo [信息] 启动应用程序...
"%PYTHON_EXE%" -c "import logging; logging.basicConfig(level=logging.DEBUG, format='%%(levelname)s: %%(message)s'); from transcriptionist_v3.ui.main_window import run_app; run_app()"

if errorlevel 1 (
    echo.
    echo [错误] 应用程序异常退出
    pause
)
