@echo off
chcp 65001 >nul
REM OpenWorkbench —— 双击即开（简易版，无崩溃自动重启；要更稳用 start_workbench.bat）。
cd /d "%~dp0"

set PYCMD=
if exist "%~dp0.python-path" for /f "usebackq delims=" %%p in ("%~dp0.python-path") do set PYCMD="%%p"
if not defined PYCMD ( where py >nul 2>nul && set PYCMD=py -3 )
if not defined PYCMD ( where python >nul 2>nul && set PYCMD=python )
if not defined PYCMD ( where python3 >nul 2>nul && set PYCMD=python3 )
if not defined PYCMD (
  echo [x] 没找到 Python 3.8+。请先安装：https://www.python.org/downloads/
  pause
  exit /b 1
)

%PYCMD% -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo [!] 找到的 Python 跑不起来（可能是应用商店的占位符）。
  echo     请装真 Python 3.8+，或在项目根目录建 .python-path 文件写上 python.exe 的完整路径。
  pause
  exit /b 1
)

echo 正在启动工作台...
start "" http://127.0.0.1:8777
%PYCMD% server.py 8777
pause
