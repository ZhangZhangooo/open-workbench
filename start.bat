@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=C:\Users\wuson\.workbuddy\binaries\python\envs\default\Scripts\python.exe
if not exist "%PY%" set PY=C:\Users\wuson\.workbuddy\binaries\python\versions\3.13.12\python.exe

echo 正在启动工作台...
start "" http://127.0.0.1:8777
"%PY%" server.py 8777
pause
