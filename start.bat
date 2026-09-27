@echo off
rem Ratica launcher for Windows: double-click to start.
rem First run installs uv (a small Python manager) and Ratica's packages; later runs start at once.
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo Installing uv, a small tool that manages Python for Ratica...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

where uv >nul 2>nul
if errorlevel 1 (
    echo Could not install uv. See https://docs.astral.sh/uv/ and try again.
    pause
    exit /b 1
)

echo Starting Ratica. The first start takes a few minutes while packages are installed...
uv run --frozen --no-dev ratica-gui
if errorlevel 1 pause
