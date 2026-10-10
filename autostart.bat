@echo off
chcp 65001 >nul
REM OpenWorkbench 静默启动（给计划任务/开机自启用的，不开浏览器、不 pause）
cd /d "%~dp0"

REM 先把残留的 server.py / guard.py 全清掉。
REM ⚠️ 不能只按端口杀：guard.py 不监听端口，只清端口的话上一只 guard 会活着
REM    并把旧版本重新拉起来（踩过）。killsrv.py 按命令行精确匹配，且不会误杀 OpenClaw。
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8777 " ^| findstr "LISTENING"') do taskkill /F /PID %%p >nul 2>nul

set PYCMD=
if exist "%~dp0.python-path" for /f "usebackq delims=" %%p in ("%~dp0.python-path") do set PYCMD="%%p"
if not defined PYCMD ( where py >nul 2>nul && set PYCMD=py -3 )
if not defined PYCMD ( where python >nul 2>nul && set PYCMD=python )
if not defined PYCMD exit /b 1

%PYCMD% killsrv.py >nul 2>nul

REM 用 guard.py 起：崩了自动重启，否则服务说没就没（白等半天才发现页面打不开）
%PYCMD% guard.py 8777
