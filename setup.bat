@echo off
setlocal
cd /d "%~dp0"
title Hireline setup
echo.
echo  Hireline setup
echo  ==============
echo.

rem --- find Python 3.10 or newer (the "py" launcher first, then "python") ---
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo  Python 3.10 or newer was not found.
  echo  Install it from https://www.python.org/downloads/  and tick "Add python.exe to PATH",
  echo  then run setup.bat again.
  echo.
  pause
  exit /b 1
)
for /f "delims=" %%v in ('%PY% -c "import sys; print(sys.version.split()[0])"') do echo  Using Python %%v

rem --- a private environment inside this folder, so nothing else on the PC is touched ---
if exist ".venv\Scripts\python.exe" (
  echo  Environment already exists: .venv
) else (
  echo  Creating environment in .venv ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo  Could not create the environment.
    pause
    exit /b 1
  )
)

echo  Installing packages ^(fastapi, uvicorn, httpx, openpyxl^) ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo  Package install failed. Check the internet connection and run setup.bat again.
  pause
  exit /b 1
)

if not exist data mkdir data

rem --- quick self-check (offline, about 20 seconds) ---
echo  Checking the install ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q pytest >nul 2>&1
".venv\Scripts\python.exe" -m pytest -q -p no:cacheprovider tests >nul 2>&1
if errorlevel 1 (
  echo  Warning: the self-check reported a problem. The app may still run; see "python -m pytest" for details.
) else (
  echo  Self-check passed.
)

echo.
echo  Setup complete. Start the app with run.bat
echo.
if /i not "%~1"=="/quiet" pause
exit /b 0
