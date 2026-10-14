@echo off
rem Double-click to check the colours of the Dataset_01 photos, piece by piece.
call "%~dp0_env.bat" || exit /b 1
"%PY%" -m bricksort.colour_review
if errorlevel 1 pause
