@echo off
rem Double-click to cut photos in my_photos\_to_cut into one picture per piece.
cd /d "%~dp0"
"%USERPROFILE%\LegoSorterData\venv\Scripts\python.exe" -m bricksort.cut
if errorlevel 1 pause
