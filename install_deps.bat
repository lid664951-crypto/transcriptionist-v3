@echo off
chcp 65001 >nul
echo 正在安装项目依赖 (requirements.txt) ...
echo.

REM 优先使用当前目录下的 python/pip（虚拟环境或嵌入 Python）
if exist "venv\Scripts\pip.exe" (
    echo 使用 venv 中的 pip
    venv\Scripts\pip.exe install -r requirements.txt
) else if exist ".venv\Scripts\pip.exe" (
    echo 使用 .venv 中的 pip
    .venv\Scripts\pip.exe install -r requirements.txt
) else (
    REM 使用系统 PATH 中的 python -m pip
    python -m pip install -r requirements.txt
)

if %ERRORLEVEL% neq 0 (
    echo.
    echo 安装失败。请确保已安装 Python 并将 pip 加入 PATH，或在本项目下创建虚拟环境后重试。
    pause
    exit /b 1
)

echo.
echo 依赖安装完成。
pause
