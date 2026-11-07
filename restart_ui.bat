@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  Restart ComfyUIGenerator UI
echo  Time: %date% %time%
echo ============================================

echo [1/3] Stopping existing UI...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\restart_ui.ps1"

timeout /t 2 /nobreak >nul

echo [2/3] Starting new UI (latest code)...
start "" "%~dp0.venv\Scripts\pythonw.exe" -m comfyui_generator.ui

timeout /t 1 /nobreak >nul

echo [3/3] New UI started at %time%.
echo If this window is from this .bat, you are running the newest build.
echo ============================================
timeout /t 3 /nobreak >nul
