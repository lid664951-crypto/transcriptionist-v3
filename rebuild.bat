@echo off
chcp 65001 >nul
echo ========================================
echo 音译家 v1.1.1 - 重新打包脚本
echo ========================================
echo.

echo [1/4] 清理旧的打包文件...
if exist "build" (
    rmdir /s /q "build"
    echo   ✓ 已删除 build 目录
)
if exist "dist" (
    rmdir /s /q "dist"
    echo   ✓ 已删除 dist 目录
)
if exist "runtime_hook_multiprocessing.py" (
    del /q "runtime_hook_multiprocessing.py"
    echo   ✓ 已删除旧的运行时钩子
)
echo.

echo [2/4] 检查 PyInstaller...
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo   ✗ PyInstaller 未安装
    echo   正在安装 PyInstaller...
    pip install pyinstaller
    if errorlevel 1 (
        echo   ✗ 安装失败，请手动安装: pip install pyinstaller
        pause
        exit /b 1
    )
)
echo   ✓ PyInstaller 已就绪
echo.

echo [3/4] 运行多进程测试...
python test_multiprocessing_frozen.py
if errorlevel 1 (
    echo.
    echo   ✗ 多进程测试失败！
    echo   请检查代码修复是否正确
    pause
    exit /b 1
)
echo.

echo [4/4] 开始打包...
pyinstaller build.spec
if errorlevel 1 (
    echo.
    echo   ✗ 打包失败！
    echo   请查看上方错误信息
    pause
    exit /b 1
)
echo.

echo ========================================
echo ✓ 打包完成！
echo ========================================
echo.
echo 输出目录: dist\音译家 AI音效管理工具1.1.1\
echo 主程序: 音译家 AI音效管理工具1.1.1.exe
echo.
echo 建议测试步骤:
echo 1. 运行主程序
echo 2. 进入 AI 检索页面
echo 3. 点击"