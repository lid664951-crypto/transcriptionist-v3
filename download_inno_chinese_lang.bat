@echo off
chcp 65001 >nul
setlocal

set "ROOT=%~dp0"
set "DIR=%ROOT%packaging\installer_lang"
set "OUT=%DIR%\ChineseSimplified.isl"
set "URL=https://raw.githubusercontent.com/jrsoftware/issrc/refs/heads/main/Files/Languages/Unofficial/ChineseSimplified.isl"

echo ============================================================
echo 下载 Inno Setup 简体中文向导语言文件
echo ============================================================
echo.
echo 目标路径: %OUT%
echo.

if not exist "%DIR%" (
  mkdir "%DIR%" >nul 2>&1
)

powershell -NoProfile -Command "& { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%URL%' -OutFile '%OUT%' -UseBasicParsing }"

if exist "%OUT%" (
  echo.
  echo ✅ 下载完成：%OUT%
  echo.
  echo 下一步：重新运行 build.bat 生成安装包（将自动启用中文向导）。
) else (
  echo.
  echo ❌ 下载失败。
  echo 你也可以手动打开下面链接，右键另存为 ChineseSimplified.isl 放到：%DIR%
  echo %URL%
)

echo.
pause
