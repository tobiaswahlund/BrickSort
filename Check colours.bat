@echo off
rem Double-click to check the colours of the Dataset_01 photos, piece by piece.
cd /d "%~dp0"
"%USERPROFILE%\LegoSorterData\venv\Scripts\python.exe" -m bricksort.colour_review
if errorlevel 1 pause
