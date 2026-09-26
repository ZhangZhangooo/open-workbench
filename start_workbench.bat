@echo off
chcp 65001 >nul
REM OpenWorkbench —— 双击即开。会拉起 guard.py（内含 server.py 崩溃自动重启）。
REM 关掉这个黑窗口 = 停止服务。
cd /d "%~dp0"

REM 找 Python：优先本机覆盖文件 .python-path（可选、不提交），否则 py / python / python3
set PYCMD=
if exist "%~dp0.python-path" for /f "usebackq delims=" %%p in ("%~dp0.python-path") do set PYCMD="%%p"
if not defined PYCMD ( where py >nul 2>nul && set PYCMD=py -3 )
if not defined PYCMD ( where python >nul 2>nul && set PYCMD=python )
if not defined PYCMD ( where python3 >nul 2>nul && set PYCMD=python3 )
if not defined PYCMD (
  echo [x] 没找到 Python 3.8+。请先安装：https://www.python.org/downloads/
  echo     装好后再双击本文件。
  pause
  exit /b 1
)

REM 校验找到的 Python 真能跑（应用商店的占位符会在这里被拦下）
%PYCMD% -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo [!] 找到的 Python 跑不起来（可能是应用商店的占位符）。
  echo     请装真 Python 3.8+，或在项目根目录建 .python-path 文件写上 python.exe 的完整路径。
  pause
  exit /b 1
)

%PYCMD% guard.py 8777
pause
