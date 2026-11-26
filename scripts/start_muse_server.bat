@echo off
chcp 65001 >nul
set SERVER=C:\Users\gg935\AppData\Local\LocModel\engines\b12707-cuda-13.5\llama-server.exe
set MODEL=G:\AI-Models\The-freezer__Muse-Glimmer-30B-Abliterated-GGUF\Muse-Glimmer-30B-Abliterated-Q4_K_M.gguf
set MMPROJ=G:\AI-Models\The-freezer__Muse-Glimmer-30B-Abliterated-GGUF\mmproj-Muse-Glimmer-30B-Abliterated-Q4_K_M.gguf
if not exist "%MODEL%" (echo model not found & exit /b 1)
echo Starting abliterated Muse (thinking ON, high) on http://127.0.0.1:8080 ...
"%SERVER%" -m "%MODEL%" --mmproj "%MMPROJ%" -ngl 999 -fa on --jinja --reasoning on --reasoning-format deepseek --reasoning-effort high --reasoning-budget -1 --host 127.0.0.1 --port 8080 -c 16384 --temp 1.0 --top-p 0.95 --top-k 64
