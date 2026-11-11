@echo off
setlocal EnableExtensions
title RootsVoice setup - nightfellas
cd /d "%~dp0"
set "HERE=%~dp0"

echo.
echo  ============================================================
echo    RootsVoice setup  -  nightfellas
echo  ============================================================
echo    Installs everything RootsVoice needs to run from this folder:
echo    Python 3.11 (if needed), the speech engine (faster-whisper)
echo    and the other components, the speech model, and a desktop
echo    shortcut. Needs internet once; takes about 5-15 minutes.
echo.
if not exist "%HERE%rootsvoice.py" goto no_app
if not exist "%HERE%requirements.txt" goto no_app

rem ------------------------------------------------------------------
echo [1/6] Looking for Python 3.10 - 3.12...
set "PYEXE="
call :findpy
if defined PYEXE goto have_py
echo       Not found - installing Python 3.11 with winget...
winget install -e --id Python.Python.3.11 --scope user --silent --accept-package-agreements --accept-source-agreements
call :findpy
if defined PYEXE goto have_py
echo.
echo   Could not install Python automatically.
echo   Install Python 3.11 from https://www.python.org/downloads/
echo   (tick "Add python.exe to PATH"), then double-click this file again.
goto fail
:have_py
echo       Using %PYEXE%

rem ------------------------------------------------------------------
echo.
echo [2/6] Creating RootsVoice's own Python environment (.venv)...
set "VPY=%HERE%.venv\Scripts\python.exe"
if not exist "%VPY%" %PYEXE% -m venv "%HERE%.venv"
if not exist "%VPY%" goto fail_venv

rem ------------------------------------------------------------------
echo.
echo [3/6] Installing the speech engine and the other components...
"%VPY%" -m pip install --upgrade pip --disable-pip-version-check
"%VPY%" -m pip install --upgrade --disable-pip-version-check -r "%HERE%requirements.txt"
if errorlevel 1 goto fail_pip

rem ------------------------------------------------------------------
echo.
echo [4/6] Checking that everything really loads...
"%VPY%" "%HERE%rootsvoice.py" --check-deps
if not errorlevel 1 goto deps_ok
echo       Installing Microsoft's Visual C++ runtime (the speech engine needs it)...
winget install -e --id Microsoft.VCRedist.2015+.x64 --silent --accept-package-agreements --accept-source-agreements
"%VPY%" "%HERE%rootsvoice.py" --check-deps
if errorlevel 1 goto fail_check
:deps_ok

rem ------------------------------------------------------------------
echo.
echo [5/6] Downloading the speech model (about 145 MB)...
"%VPY%" "%HERE%rootsvoice.py" --download-model base.en
if errorlevel 1 echo       Download failed - RootsVoice will download it the first time you press Start.

rem ------------------------------------------------------------------
echo.
echo [6/6] Making a desktop shortcut...
"%VPY%" "%HERE%rootsvoice.py" --make-shortcut

echo.
echo  ============================================================
echo    Done! Start RootsVoice from the "RootsVoice" icon on your
echo    desktop, or double-click RootsVoice.bat in this folder.
echo  ============================================================
echo.
start "" "%HERE%.venv\Scripts\pythonw.exe" "%HERE%rootsvoice.py"
pause
exit /b 0

:no_app
echo.
echo   Put this file in the same folder as rootsvoice.py and
echo   requirements.txt, then double-click it again.
goto fail

:fail_venv
echo.
echo   Could not create RootsVoice's Python environment with %PYEXE%.
goto fail

:fail_pip
echo.
echo   Installing the components failed - scroll up to see why.
echo   * "Failed to establish a new connection": check the internet.
echo   * "No matching distribution": delete the .venv folder here and
echo     run this file again (it will use Python 3.10 - 3.12).
goto fail

:fail_check
echo.
echo   Some components don't load - see the lines marked FIX above.
goto fail

:fail
echo.
echo   Fix the problem above and double-click setup_rootsvoice.bat
echo   again - finished steps are skipped.
echo.
pause
exit /b 1

rem ------------------------------------------------------------------
:findpy
for %%V in (3.12 3.11 3.10) do if not defined PYEXE py -%%V -c "import sys" >nul 2>&1 && set "PYEXE=py -%%V"
if defined PYEXE exit /b 0
for %%P in ("%LocalAppData%\Programs\Python\Python312\python.exe" "%LocalAppData%\Programs\Python\Python311\python.exe" "%LocalAppData%\Programs\Python\Python310\python.exe" "%ProgramFiles%\Python312\python.exe" "%ProgramFiles%\Python311\python.exe") do if not defined PYEXE if exist %%P set "PYEXE="%%~P""
exit /b 0
