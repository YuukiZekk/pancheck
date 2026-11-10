# 一键建虚拟环境并装依赖（在 Windows 本机 PowerShell 里跑）
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Write-Host "OK: 环境就绪，启动用 start.ps1"
