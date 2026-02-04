@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   清空数据库脚本
echo ============================================================
echo.
echo 此脚本将清空所有数据库数据，但保留模型文件
echo.
pause

REM 优先使用项目中内置的 Python（runtime\python\python.exe）
if exist "runtime\python\python.exe" (
    echo 使用项目内置 Python: runtime\python\python.exe
    runtime\python\python.exe scripts/clear_database.py
    goto :end
)

REM 其次尝试系统 python
where python >nul 2>&1
if %ERRORLEVEL% == 0 (
    python scripts/clear_database.py
    goto :end
)

REM 再尝试 Windows Python Launcher
where py >nul 2>&1
if %ERRORLEVEL% == 0 (
    py scripts/clear_database.py
    goto :end
)

echo.
echo ❌ 错误：找不到 Python 解释器
echo.
echo 请确保项目内置 Python 存在：runtime\python\python.exe
echo 或安装 Python 并添加到系统 PATH，或使用 py 命令
echo.
echo 手动删除方法：
echo - 删除 data\database\*.db* 文件
echo - 清空 data\index\、data\cache\、data\projects\、data\backups\
echo - 保留 data\models\（模型文件）
echo.

:end
pause
