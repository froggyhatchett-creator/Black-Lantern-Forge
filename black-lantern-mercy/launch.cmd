@echo off
cd /d "%~dp0"
py -3 -m mercy
if errorlevel 1 pause
