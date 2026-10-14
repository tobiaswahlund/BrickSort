@echo off
rem Double-click to watch the training pictures appear while they're being made.
cd /d "%~dp0"
"%USERPROFILE%\LegoSorterData\venv\Scripts\python.exe" -m bricksort.watch
if errorlevel 1 pause
