@echo off
chcp 65001 >nul
title 验证修复 - Transcriptionist v3

cd /d "%~dp0"

echo ========================================
echo   验证数据库和导入修复
echo ========================================
echo.

set PYTHON_EXE=runtime\python\python.exe

if not exist "%PYTHON_EXE%" (
    echo [错误] 未找到内嵌Python: %PYTHON_EXE%
    pause
    exit /b 1
)

echo [1/2] 运行数据库诊断...
echo.
"%PYTHON_EXE%" diagnose_db.py
if errorlevel 1 (
    echo.
    echo [错误] 数据库测试失败
    pause
    exit /b 1
)

echo.
echo ========================================
echo.
echo [2/2] 运行应用程序集成测试...
echo.
"%PYTHON_EXE%" test_app.py
if errorlevel 1 (
    echo.
    echo [错误] 应用程序测试失败
    pause
    exit /b 1
)

echo.
echo ========================================
echo   ✓ 所有测试通过！
echo   数据库和导入问题已修复
echo ========================================
echo.
echo 现在可以运行 run_qt.bat 启动应用程序
echo.
pause
