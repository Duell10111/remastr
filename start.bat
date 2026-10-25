@echo off
rem Double-click launcher for start.ps1; keeps the window open if startup fails.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 pause
