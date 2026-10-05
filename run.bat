@echo off
setlocal
cd /d "%~dp0"
title Hireline

if not defined HIRELINE_PORT set "HIRELINE_PORT=8100"

rem --- first run on this PC: set everything up automatically ---
if not exist ".venv\Scripts\python.exe" (
  echo  First run on this PC: running setup ...
  call "%~dp0setup.bat" /quiet
  if errorlevel 1 exit /b 1
)

rem --- stop early if the port is taken (for example Hireline is already open) ---
netstat -ano | findstr /r /c:"127.0.0.1:%HIRELINE_PORT% .*LISTENING" >nul
if not errorlevel 1 (
  echo  Port %HIRELINE_PORT% is already in use - Hireline may already be running.
  echo  Opening http://127.0.0.1:%HIRELINE_PORT% ...
  start "" "http://127.0.0.1:%HIRELINE_PORT%"
  echo  To use another port:  set HIRELINE_PORT=8200  then run run.bat
  timeout /t 8 >nul
  exit /b 0
)

echo.
echo  Hireline is running at http://127.0.0.1:%HIRELINE_PORT%
echo  Keep this window open while you use it. Close it (or press Ctrl+C) to stop.
echo.
rem open the browser a moment after the server starts
start "" /b cmd /c "timeout /t 3 >nul & start "" http://127.0.0.1:%HIRELINE_PORT%"
".venv\Scripts\python.exe" -m uvicorn hireline.app:app --host 127.0.0.1 --port %HIRELINE_PORT%
if errorlevel 1 pause
