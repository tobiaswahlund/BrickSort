@echo off
rem Double-click to watch the training pictures appear while they're being made.
call "%~dp0_env.bat" || exit /b 1
"%PY%" -m bricksort.watch
if errorlevel 1 pause
