@echo off
rem Double-click to open the virtual sorting machine (conveyor belt + bins).
call "%~dp0_env.bat" || exit /b 1
"%PY%" -m bricksort.conveyor_demo
if errorlevel 1 pause
