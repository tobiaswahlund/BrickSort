@echo off
rem Double-click to look through the training pictures: the ones being made now, or all of them.
call "%~dp0_env.bat" || exit /b 1
"%PY%" -m bricksort.watch
if errorlevel 1 pause
