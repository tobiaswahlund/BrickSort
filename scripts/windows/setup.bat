@echo off
rem One-time setup on a new Windows computer: installs Python and the libraries BrickSort needs.
rem Afterwards, double-click "Start demo.bat" or "Start sorting machine.bat".
call "%~dp0_env.bat" setup
cd /d "%PROJECT%"
set "PYBASE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "VENV=%DATA%\venv"

if not exist "%PYBASE%" (
    echo Installing Python 3.12 ...
    winget install --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
)
if not exist "%PYBASE%" (
    echo Could not install Python automatically. Install Python 3.12 from python.org, then run this again.
    pause
    exit /b 1
)

if not exist "%VENV%\Scripts\python.exe" (
    echo Creating a private Python environment in %VENV% ...
    "%PYBASE%" -m venv "%VENV%"
)
"%PY%" -m pip install --upgrade pip

where nvidia-smi >nul 2>nul
if %errorlevel%==0 (
    echo NVIDIA graphics card found: installing the fast graphics-card version of PyTorch, about 2.5 GB ...
    "%PY%" -m pip install "torch>=2.6" torchvision --index-url https://download.pytorch.org/whl/cu126
) else (
    echo No NVIDIA graphics card: installing the regular version of PyTorch, about 250 MB ...
    "%PY%" -m pip install "torch>=2.6" torchvision --index-url https://download.pytorch.org/whl/cpu
)
rem the rest (mujoco, numpy, pillow), and BrickSort itself as an editable install: it runs from this folder
"%PY%" -m pip install -e "%PROJECT%"

echo.
echo Downloading the LEGO part library and part lists, about 160 MB ...
"%PY%" -c "from bricksort import catalog, ldraw; ldraw.Library(); catalog.colors(); catalog.twins(); [catalog.read_csv(n) for n in ('parts', 'part_categories', 'inventory_parts')]; print('Done')"

if not exist "%PROJECT%\reference" (
    echo.
    echo Making a reference picture of every part, about 2 minutes ...
    "%PY%" -m bricksort.render references
)

echo.
if not exist "%PROJECT%\model\lego_model.pt" (
    echo Downloading the trained model, about 25 MB ...
    "%PY%" -m bricksort.get_model
)

echo.
echo All set! Double-click "Start demo.bat" or "Start sorting machine.bat".
pause
