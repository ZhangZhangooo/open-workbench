@echo off
chcp 65001 >nul
REM OpenWorkbench —— 双击即开。会拉起 guard.py，服务崩了自动重启。
cd /d "%~dp0"

REM 先把占着 8777 的旧实例清掉。Windows 的 SO_REUSEADDR 允许两个进程同绑一个端口，
REM 不清的话新实例起不来、请求还被旧实例应答，改了配置就像没改一样。
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8777 " ^| findstr "LISTENING"') do taskkill /F /PID %%p >nul 2>nul

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

REM 清掉残留的 guard.py —— 它不监听端口，只按端口清是杀不到它的，
REM 留着就会把旧版本重新拉回来（踩过：旧副本的 guard 一直保活着老代码）。
%PYCMD% killsrv.py >nul 2>nul

echo 正在启动工作台...
start "" http://127.0.0.1:8777
REM 用 guard.py 而不是 server.py：崩了能自动重启，省得页面突然打不开
%PYCMD% guard.py 8777
pause
