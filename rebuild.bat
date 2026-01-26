@echo off
chcp 65001 >nul
echo ============================================================
echo 音译家 - 快速重新打包
echo ============================================================
echo.

set PYTHON_EXE=runtime\python\python.exe

echo [1/3] 清理旧文件...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo ✅ 清理完成
echo.

echo [2/3] 开始打包...
echo    请耐心等待...
echo.
%PYTHON_EXE% -m PyInstaller build.spec
if errorlevel 1 (
    echo ❌ 打包失败
    pause
    exit /b 1
)
echo ✅ 打包完成
echo.

echo [3/3] 打包结果:
echo.
if exist "dist\音译家\音译家.exe" (
    echo ✅ 成功！可执行文件已生成
    echo.
    echo 📁 输出目录: dist\音译家\
    echo 📦 主程序: dist\音译家\音译家.exe
    echo.
    echo ============================================================
    echo 重新打包完成！
    echo ============================================================
    echo.
    echo 现在可以在另一台电脑上测试了
    echo.
) else (
    echo ❌ 错误: 未找到可执行文件
)

pause
