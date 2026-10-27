@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" -m comfyui_generator.ui
if errorlevel 1 pause
