@echo off
rem Double-click to train the model: make the training pictures, train, pause and carry on, and look at the pictures.
call "%~dp0_env.bat" || exit /b 1
"%PY%" -m bricksort.training_app
if errorlevel 1 pause
