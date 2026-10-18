@echo off
rem Double-click to open BrickSort: one menu with every part of the project.
call "%~dp0_env.bat" || exit /b 1
start "" "%DATA%\venv\Scripts\pythonw.exe" -m bricksort.app
