@echo off
rem Double-click this file to open the LegoSorter virtual demo.
cd /d "%~dp0"
"%USERPROFILE%\LegoSorterData\venv\Scripts\python.exe" -m legosorter.demo
if errorlevel 1 pause
