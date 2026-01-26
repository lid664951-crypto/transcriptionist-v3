@echo off
chcp 65001 >nul
echo ========================================
echo   调试命名规则页面
echo ========================================
echo.

.\runtime\python\python.exe -c "import sys; import logging; logging.basicConfig(level=logging.DEBUG, format='%%(levelname)s: %%(message)s', stream=sys.stderr); from transcriptionist_v3.ui.main_window import run_app; run_app()" 2>&1

echo.
echo [调试完成]
pause
