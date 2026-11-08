@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  Close ALL ComfyUIGenerator UI instances
echo  Time: %date% %time%
echo ============================================

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\close_all_ui.ps1"

echo ============================================
echo Done at %time%.
timeout /t 3 /nobreak >nul
