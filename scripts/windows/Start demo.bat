@echo off
rem Double-click to open the BrickSort demo: drop a piece, see the model's guesses.
call "%~dp0_env.bat" || exit /b 1
"%PY%" -m bricksort.demo
if errorlevel 1 pause
