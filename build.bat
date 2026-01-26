@echo off
chcp 65001 >nul
echo ============================================================
echo 音译家 v1.0.0 - 自动打包脚本
echo ============================================================
echo.

:: 设置内嵌 Python 路径
set PYTHON_EXE=runtime\python\python.exe

:: 检查内嵌 Python
if not exist "%PYTHON_EXE%" (
    echo ❌ 错误: 未找到内嵌 Python
    echo    路径: %PYTHON_EXE%
    echo    请确保项目完整
    pause
    exit /b 1
)

echo ✅ 找到内嵌 Python
%PYTHON_EXE% --version
echo.

:: 步骤 1: 安装打包工具
echo [1/5] 安装打包工具...
%PYTHON_EXE% -m pip install pyinstaller pillow --quiet
if errorlevel 1 (
    echo ❌ 安装失败
    pause
    exit /b 1
)
echo ✅ 打包工具已安装
echo.

:: 步骤 2: 转换图标
echo [2/5] 转换图标...
%PYTHON_EXE% convert_icon.py
if errorlevel 1 (
    echo ⚠️  警告: 图标转换失败，将使用默认图标
)
echo.

:: 步骤 3: 清理旧文件
echo [3/5] 清理旧文件...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo ✅ 清理完成
echo.

:: 步骤 4: 执行打包
echo [4/5] 开始打包...
echo    这可能需要几分钟，请耐心等待...
echo.
%PYTHON_EXE% -m PyInstaller build.spec
if errorlevel 1 (
    echo ❌ 打包失败
    pause
    exit /b 1
)
echo ✅ 打包完成
echo.

:: 步骤 5: 显示结果
echo [5/5] 打包结果:
echo.
if exist "dist\音译家 AI 音效管理工具\音译家.exe" (
    echo ✅ 成功！可执行文件已生成
    echo.
    echo 📁 输出目录: dist\音译家 AI 音效管理工具\
    echo 📦 主程序: dist\音译家 AI 音效管理工具\音译家.exe
    echo.
    
    :: 显示文件大小
    for %%F in ("dist\音译家 AI 音效管理工具\音译家.exe") do (
        set size=%%~zF
        set /a sizeMB=!size! / 1048576
        echo 📊 程序大小: !sizeMB! MB
    )
    
    echo.
    echo ============================================================
    echo 打包完成！
    echo ============================================================
    echo.
    echo 下一步:
    echo 1. 测试程序: cd "dist\音译家 AI 音效管理工具" ^&^& 音译家.exe
    echo 2. 创建安装包: 使用 Inno Setup 编译 installer.iss
    echo 3. 分发给用户
    echo.
    
    :: 询问是否立即测试
    set /p test="是否立即运行测试？(Y/N): "
    if /i "%test%"=="Y" (
        echo.
        echo 启动程序...
        start "" "dist\音译家 AI 音效管理工具\音译家.exe"
    )
) else (
    echo ❌ 错误: 未找到可执行文件
    echo    请检查打包日志
)

echo.
pause
