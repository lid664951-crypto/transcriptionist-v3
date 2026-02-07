@echo off
setlocal

REM NOTE:
REM Keep this script ASCII-only to avoid cmd.exe encoding issues.
REM Output filenames (Chinese) are controlled by build.spec / installer.iss.

chcp 65001 >nul
REM Force Python to output UTF-8 to avoid GBK/Unicode issues
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

REM Enable installer build by default (set BUILD_INSTALLER=0 to disable)
if not defined BUILD_INSTALLER set "BUILD_INSTALLER=1"

echo ============================================================
echo Build script (PyInstaller + Inno Setup Installer)
echo ============================================================
echo.

REM Generate log file name
set "LOG_FILE=build_log.txt"
echo Build log will be saved to: %LOG_FILE%
echo ============================================================ > "%LOG_FILE%"
echo Build script (PyInstaller + Inno Setup Installer) >> "%LOG_FILE%"
echo Started at: %date% %time% >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

set "PYTHON_EXE=runtime\python\python.exe"

if not exist "%PYTHON_EXE%" (
  echo ERROR: embedded python not found: %PYTHON_EXE%
  echo ERROR: embedded python not found: %PYTHON_EXE% >> "%LOG_FILE%"
  echo Please ensure the project is complete.
  echo Please ensure the project is complete. >> "%LOG_FILE%"
  pause
  exit /b 1
)

echo Embedded python:
echo Embedded python: >> "%LOG_FILE%"
"%PYTHON_EXE%" --version
"%PYTHON_EXE%" --version >> "%LOG_FILE%" 2>&1
echo. >> "%LOG_FILE%"
echo.

echo [1/6] Install build tools...
echo [1/6] Install build tools... >> "%LOG_FILE%"
"%PYTHON_EXE%" -m pip install pyinstaller pillow --quiet
"%PYTHON_EXE%" -m pip install pyinstaller pillow --quiet >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo ERROR: pip install failed.
  echo ERROR: pip install failed. >> "%LOG_FILE%"
  pause
  exit /b 1
)
REM Ensure packaging is complete
echo Upgrading packaging...
echo Upgrading packaging... >> "%LOG_FILE%"
"%PYTHON_EXE%" -m pip install --upgrade packaging --quiet
"%PYTHON_EXE%" -m pip install --upgrade packaging --quiet >> "%LOG_FILE%" 2>&1
echo. >> "%LOG_FILE%"
echo.

echo [2/6] Convert icon...
echo [2/6] Convert icon... >> "%LOG_FILE%"
"%PYTHON_EXE%" convert_icon.py
"%PYTHON_EXE%" convert_icon.py >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo ERROR: convert_icon.py failed.
  echo ERROR: convert_icon.py failed. >> "%LOG_FILE%"
  echo Check above traceback in %LOG_FILE%
  pause
  exit /b 1
)
echo. >> "%LOG_FILE%"
echo.

echo [3/6] Clean output...
echo [3/6] Clean output... >> "%LOG_FILE%"
REM Force delete build and dist directories
if exist build (
  rmdir /s /q build 2>nul
  if exist build powershell -Command "Remove-Item -Path 'build' -Recurse -Force -ErrorAction SilentlyContinue"
)
if exist dist (
  rmdir /s /q dist 2>nul
  if exist dist powershell -Command "Remove-Item -Path 'dist' -Recurse -Force -ErrorAction SilentlyContinue"
)
echo Cleaned build and dist directories. >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"
echo.

echo [4/6] PyInstaller build...
echo [4/6] PyInstaller build... >> "%LOG_FILE%"
echo PyInstaller output will be saved to log file...
echo PyInstaller output will be saved to log file... >> "%LOG_FILE%"
echo.
echo TIP: PyInstaller may take 10-30 minutes. Do not close this window.
echo      Check build_log.txt for progress if the console seems idle.
echo.
echo TIP: PyInstaller may take 10-30 minutes... >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"
echo.
"%PYTHON_EXE%" -m PyInstaller build.spec -y >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo ERROR: PyInstaller build failed. >> "%LOG_FILE%"
  echo ERROR: PyInstaller build failed.
  echo.
  echo Detailed error saved to: %LOG_FILE%
  pause
  exit /b 1
)
echo. >> "%LOG_FILE%"
echo.

echo [5/6] Build installer (Inno Setup)...
echo [5/6] Build installer (Inno Setup)... >> "%LOG_FILE%"

REM Find Inno Setup Compiler (ISCC.exe)
set "ISCC="
REM 2. Try standard locations if not found in PATH
if not "%ISCC%"=="" goto :found_iscc
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files (x86)\Inno Setup 5\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 5\ISCC.exe"
REM Also check local app data or other common user install paths if needed

if "%BUILD_INSTALLER%"=="1" (
  if not "%ISCC%"=="" (
    :found_iscc
    echo Building installer with: %ISCC%
    echo Building installer with: %ISCC% >> "%LOG_FILE%"
    "%ISCC%" "installer.iss" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 (
      echo WARNING: installer build failed. Check installer.iss output above.
      echo WARNING: installer build failed. >> "%LOG_FILE%"
    ) else (
      echo Installer build OK.
      echo Installer build OK. >> "%LOG_FILE%"
    )
  ) else (
    echo WARNING: Inno Setup not detected. Skipping installer build.
    echo WARNING: Inno Setup not detected. >> "%LOG_FILE%"
    echo Install Inno Setup and rerun this script if you need a setup.exe.
  )
) else (
  echo Skipped - installer build disabled.
  echo Skipped - installer build disabled. >> "%LOG_FILE%"
  echo To enable: set BUILD_INSTALLER=1
)
echo. >> "%LOG_FILE%"
echo.

echo [6/6] Done. Check the dist\ folder for the portable version.
echo [6/6] Done. Check the dist\ folder for the portable version. >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"
echo Build completed at: %date% %time% >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"
echo.
echo ============================================================
echo Build log saved to: %LOG_FILE%
echo ============================================================
echo.
pause
