@echo off
chcp 65001 >nul
REM OpenWorkbench 静默启动（给计划任务/开机自启用的，不开浏览器、不 pause）
cd /d "%~dp0"

set PYCMD=
if exist "%~dp0.python-path" for /f "usebackq delims=" %%p in ("%~dp0.python-path") do set PYCMD="%%p"
if not defined PYCMD ( where py >nul 2>nul && set PYCMD=py -3 )
if not defined PYCMD ( where python >nul 2>nul && set PYCMD=python )
if not defined PYCMD exit /b 1

%PYCMD% server.py 8777
