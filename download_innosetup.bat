@echo off
chcp 65001 >nul
echo 正在下载 Inno Setup 6.7.0 ...
echo.

:: 官方直链（jrsoftware 文件服务器）
set "URL=https://files.jrsoftware.org/is/6/innosetup-6.7.0.exe"
set "OUT=%~dp0innosetup-6.7.0.exe"

powershell -NoProfile -Command "& { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%URL%' -OutFile '%OUT%' -UseBasicParsing }"

if exist "%OUT%" (
    echo.
    echo 下载完成: %OUT%
    echo 双击 innosetup-6.7.0.exe 安装，装好后重新运行 build.bat 即可生成安装包。
    start "" "%OUT%"
) else (
    echo 下载失败，请手动打开浏览器访问：
    echo https://jrsoftware.org/isdl.php
    echo 下载 innosetup-6.7.0.exe 到当前目录。
)
echo.
pause
