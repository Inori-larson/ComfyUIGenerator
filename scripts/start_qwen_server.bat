@echo off
chcp 65001 >nul
set SERVER=C:\Users\gg935\AppData\Local\LocModel\engines\b12707-cuda-13.5\llama-server.exe
set MODEL=G:\AI-Models\huihui-ai__Huihui-Qwen3.8-27B-abliterated-GGUF\Huihui-Qwen3.8-27B-abliterated-UD-Q2_K_XL.gguf
set MMPROJ=G:\AI-Models\huihui-ai__Huihui-Qwen3.8-27B-abliterated-GGUF\mmproj-model-bf16.gguf
if not exist "%MODEL%" (echo model not found & exit /b 1)
echo Starting abliterated Qwen3.8 (thinking ON, medium, optimized) on http://127.0.0.1:8080 ...
"%SERVER%" -m "%MODEL%" --mmproj "%MMPROJ%" -ngl 999 -fa on --jinja --reasoning on --reasoning-format deepseek --reasoning-effort medium --reasoning-budget 4096 --host 127.0.0.1 --port 8080 -c 32768 --temp 0.6 --top-p 0.9 --top-k 40
