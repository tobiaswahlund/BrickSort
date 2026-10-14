@echo off
rem Double-click to make the new training pictures and then train the model.
rem You can close this window at any time (or turn the computer off).
rem Double-click again later and it carries on where it stopped:
rem   pictures already made are kept, and training continues from the last finished round.
call "%~dp0_env.bat" || exit /b 1
echo Step 1 of 2: making training pictures (skips the ones already made) ...
"%PY%" -m bricksort.render 100
if errorlevel 1 goto failed
echo.
echo Step 2 of 2: training (10 rounds; progress is saved after every round) ...
"%PY%" -m bricksort.train 10
if errorlevel 1 goto failed
echo.
echo All done! The sorting machine and the demo now use the new model.
pause
exit /b 0
:failed
echo.
echo Something went wrong (see above). Double-click Train.bat again to carry on.
pause
