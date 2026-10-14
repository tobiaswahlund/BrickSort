@echo off
rem One-time setup on a new Windows computer: installs Python and the libraries LegoSorter needs.
rem Afterwards, double-click "Start demo.bat" or "Start sorting machine.bat".
cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "VENV=%USERPROFILE%\LegoSorterData\venv"

if not exist "%PY%" (
    echo Installing Python 3.12 ...
    winget install --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
)
if not exist "%PY%" (
    echo Could not install Python automatically. Install Python 3.12 from python.org, then run this again.
    pause
    exit /b 1
)

if not exist "%VENV%\Scripts\python.exe" (
    echo Creating a private Python environment in %VENV% ...
    "%PY%" -m venv "%VENV%"
)
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip

where nvidia-smi >nul 2>nul
if %errorlevel%==0 (
    echo NVIDIA graphics card found: installing the fast graphics-card version of PyTorch, about 2.5 GB ...
    "%VENV%\Scripts\python.exe" -m pip install "torch>=2.6" torchvision --index-url https://download.pytorch.org/whl/cu126
) else (
    echo No NVIDIA graphics card: installing the regular version of PyTorch, about 250 MB ...
    "%VENV%\Scripts\python.exe" -m pip install "torch>=2.6" torchvision --index-url https://download.pytorch.org/whl/cpu
)
"%VENV%\Scripts\python.exe" -m pip install "mujoco>=3.2,<4" numpy pillow

echo.
echo Downloading the Lego part library and part lists, about 160 MB ...
"%VENV%\Scripts\python.exe" -c "from legosorter import catalog, ldraw; ldraw.Library(); catalog.colors(); catalog.twins(); print('Done')"

echo.
echo All set! Double-click "Start demo.bat" or "Start sorting machine.bat".
pause
