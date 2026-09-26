@echo off
REM OpenWorkbench —— 双击即开。会拉起 guard.py（内含 server.py 崩溃自动重启）。
REM 关掉这个黑窗口 = 停止服务。
cd /d "%~dp0"
"C:\Users\wuson\.workbuddy\binaries\python\versions\3.13.12\python.exe" guard.py 8777
