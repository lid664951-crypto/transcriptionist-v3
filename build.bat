@echo off
setlocal EnableDelayedExpansion

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

echo [1/8] Preflight check (required source assets)...
echo [1/8] Preflight check (required source assets)... >> "%LOG_FILE%"
set "REQUIRED_SOURCE_DIRS=ui\resources\icons ui\resources\images ui\resources\styles resources\fonts locale plugins data\models\onnx_preprocess"
for %%D in (%REQUIRED_SOURCE_DIRS%) do (
  if not exist "%%~D" (
    echo ERROR: Missing required source directory: %%~D
    echo ERROR: Missing required source directory: %%~D >> "%LOG_FILE%"
    pause
    exit /b 1
  )
)
echo Preflight source check passed.
echo Preflight source check passed. >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"
echo.

echo [2/8] Install build tools...
echo [2/8] Install build tools... >> "%LOG_FILE%"
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

echo [3/8] Convert icon...
echo [3/8] Convert icon... >> "%LOG_FILE%"
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

echo [4/8] Clean output...
echo [4/8] Clean output... >> "%LOG_FILE%"
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

echo [5/8] PyInstaller build...
echo [5/8] PyInstaller build... >> "%LOG_FILE%"
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

echo [6/8] Verify packaged layout...
echo [6/8] Verify packaged layout... >> "%LOG_FILE%"
set "DIST_MAIN_DIR="
for /d %%D in ("dist\*") do (
  if not defined DIST_MAIN_DIR if exist "%%~fD\*.exe" set "DIST_MAIN_DIR=%%~fD"
)

if not defined DIST_MAIN_DIR (
  echo ERROR: Could not detect packaged portable directory under dist\
  echo ERROR: Could not detect packaged portable directory under dist\ >> "%LOG_FILE%"
  pause
  exit /b 1
)

echo Detected portable directory: %DIST_MAIN_DIR%
echo Detected portable directory: %DIST_MAIN_DIR% >> "%LOG_FILE%"

set "VERIFY_FAIL=0"
set "REQUIRED_PACKAGED_DIRS=ui\resources\icons ui\resources\images ui\resources\styles resources\fonts locale plugins data\models\onnx_preprocess"
for %%D in (%REQUIRED_PACKAGED_DIRS%) do (
  powershell -NoProfile -Command ^
    "$base=[IO.Path]::GetFullPath('%DIST_MAIN_DIR%');" ^
    "$p1=Join-Path $base '%%~D';" ^
    "$p2=Join-Path (Join-Path $base '_internal') '%%~D';" ^
    "if((Test-Path -LiteralPath $p1) -or (Test-Path -LiteralPath $p2)){exit 0}else{exit 1}" >nul 2>&1
  if errorlevel 1 (
    echo ERROR: Missing packaged directory: %%~D
    echo ERROR: Missing packaged directory: %%~D >> "%LOG_FILE%"
    set "VERIFY_FAIL=1"
  )
)

if not exist "%DIST_MAIN_DIR%\metadata_worker.exe" (
  echo ERROR: Missing metadata_worker.exe in packaged output.
  echo ERROR: Missing metadata_worker.exe in packaged output. >> "%LOG_FILE%"
  set "VERIFY_FAIL=1"
)

set "MAIN_EXE_FOUND="
for %%E in ("%DIST_MAIN_DIR%\*.exe") do (
  if exist "%%~fE" (
    if /I not "%%~nxE"=="metadata_worker.exe" set "MAIN_EXE_FOUND=1"
  )
)
if not defined MAIN_EXE_FOUND (
  echo ERROR: Main app executable not found in packaged output.
  echo ERROR: Main app executable not found in packaged output. >> "%LOG_FILE%"
  set "VERIFY_FAIL=1"
)

if "%VERIFY_FAIL%"=="1" (
  echo ERROR: Packaged layout verification failed.
  echo ERROR: Packaged layout verification failed. >> "%LOG_FILE%"
  pause
  exit /b 1
)

echo Packaged layout verification passed.
echo Packaged layout verification passed. >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"
echo.

echo [7/8] Build installer (Inno Setup)...
echo [7/8] Build installer (Inno Setup)... >> "%LOG_FILE%"

REM Find Inno Setup Compiler (ISCC.exe)
set "ISCC="

REM 1) Try PATH first
for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do (
  if not defined ISCC set "ISCC=%%I"
)

REM 2) Try standard locations
if not defined ISCC if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "C:\Program Files (x86)\Inno Setup 5\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 5\ISCC.exe"

if /I "%BUILD_INSTALLER%"=="0" (
  echo Skipped - installer build disabled.
  echo Skipped - installer build disabled. >> "%LOG_FILE%"
  echo To enable: set BUILD_INSTALLER=1
  goto installer_step_done
)

if not defined ISCC (
  echo WARNING: Inno Setup not detected. Skipping installer build.
  echo WARNING: Inno Setup not detected. >> "%LOG_FILE%"
  echo Install Inno Setup and rerun this script if you need a setup.exe.
  goto installer_step_done
)

echo Building installer with: %ISCC%
echo Building installer with: %ISCC% >> "%LOG_FILE%"
"%ISCC%" "installer.iss" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
  echo WARNING: installer build failed, retrying with timestamp output name...
  echo WARNING: installer build failed, retrying with timestamp output name... >> "%LOG_FILE%"
  for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%T"
  "%ISCC%" "/Fsetup_%STAMP%" "installer.iss" >> "%LOG_FILE%" 2>&1
  if errorlevel 1 (
    echo WARNING: installer retry still failed. Check installer.iss output above.
    echo WARNING: installer retry still failed. >> "%LOG_FILE%"
  ) else (
    echo Installer build OK (timestamp filename).
    echo Installer build OK (timestamp filename). >> "%LOG_FILE%"
  )
) else (
  echo Installer build OK.
  echo Installer build OK. >> "%LOG_FILE%"
)

:installer_step_done
echo. >> "%LOG_FILE%"
echo.

echo [8/8] Done. Check the dist\ folder for the portable version.
echo [8/8] Done. Check the dist\ folder for the portable version. >> "%LOG_FILE%"
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
