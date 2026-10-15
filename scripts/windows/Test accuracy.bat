@echo off
rem Double-click to score the model on the test pieces in my_photos\_test (writes results\RESULTS.md).
call "%~dp0_env.bat" || exit /b 1
"%PY%" -m bricksort.evaluate
pause
