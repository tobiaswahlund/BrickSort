@echo off
rem Double-click this file to open the virtual sorting machine (conveyor belt + bins).
cd /d "%~dp0"
"%USERPROFILE%\LegoSorterData\venv\Scripts\python.exe" -m bricksort.conveyor_demo
if errorlevel 1 pause
