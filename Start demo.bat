@echo off
rem Double-click this file to open the BrickSort virtual demo.
cd /d "%~dp0"
"%USERPROFILE%\LegoSorterData\venv\Scripts\python.exe" -m bricksort.demo
if errorlevel 1 pause
