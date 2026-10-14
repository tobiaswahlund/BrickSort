@echo off
rem Shared by the other launchers (not meant to be double-clicked): finds the project folder,
rem the data folder (same rules as bricksort/config.py) and the Python environment in it.
rem Set BRICKSORT_DATA to use another data folder.
for %%I in ("%~dp0..\..") do set "PROJECT=%%~fI"
if defined BRICKSORT_DATA (
    set "DATA=%BRICKSORT_DATA%"
) else if defined LEGOSORTER_DATA (
    set "DATA=%LEGOSORTER_DATA%"
) else if exist "%USERPROFILE%\LegoSorterData" (
    set "DATA=%USERPROFILE%\LegoSorterData"
) else (
    set "DATA=%USERPROFILE%\BrickSortData"
)
set "PY=%DATA%\venv\Scripts\python.exe"
if "%~1"=="setup" exit /b 0
if not exist "%PY%" (
    echo No Python environment found in "%DATA%".
    echo Double-click setup.bat first.
    pause
    exit /b 1
)
cd /d "%PROJECT%"
exit /b 0
