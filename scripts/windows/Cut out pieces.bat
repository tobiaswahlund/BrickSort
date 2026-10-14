@echo off
rem Double-click to cut photos in my_photos\_to_cut into one picture per piece.
call "%~dp0_env.bat" || exit /b 1
"%PY%" -m bricksort.cut
if errorlevel 1 pause
