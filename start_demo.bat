@echo off
setlocal
chcp 65001 >nul
set "PYTHONDONTWRITEBYTECODE=1"
if defined SINSR_PYTHON goto run
if exist "%~dp0python_path.local.txt" goto local_python
if exist "%~dp0.venv\Scripts\python.exe" goto venv_python
if defined CONDA_PREFIX goto conda_python
set "SINSR_PYTHON=python"
goto run
:local_python
set /p "SINSR_PYTHON="<"%~dp0python_path.local.txt"
goto run
:venv_python
set "SINSR_PYTHON=%~dp0.venv\Scripts\python.exe"
goto run
:conda_python
set "SINSR_PYTHON=%CONDA_PREFIX%\python.exe"
:run
pushd "%~dp0"
if errorlevel 1 goto bad_directory
"%SINSR_PYTHON%" -B app.py %*
set "SINSR_EXIT_CODE=%ERRORLEVEL%"
popd
if not "%SINSR_EXIT_CODE%"=="0" goto failed
exit /b 0
:bad_directory
echo Cannot open the demo directory.
pause
exit /b 1
:failed
echo Demo stopped. Read README.md and run setup_demo.ps1 in your Python environment.
pause
exit /b %SINSR_EXIT_CODE%
