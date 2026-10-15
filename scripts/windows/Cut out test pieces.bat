@echo off
rem Double-click to label the pieces for the honest accuracy test (photos in my_photos\_to_cut_test).
rem The model's guesses are hidden, and the pieces go to my_photos\_test, which training never uses.
call "%~dp0_env.bat" || exit /b 1
"%PY%" -m bricksort.cut --test
if errorlevel 1 pause
