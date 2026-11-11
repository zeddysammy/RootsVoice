@echo off
setlocal EnableExtensions
title RootsVoice - building the installer (nightfellas)
cd /d "%~dp0"
set "ROOT=%~dp0"
if not exist "%ROOT%build" mkdir "%ROOT%build"

echo.
echo  ============================================================
echo    RootsVoice installer builder  -  nightfellas
echo  ============================================================
echo    Builds RootsVoice-Setup-2.1.exe. Needs internet and takes
echo    about 10-20 minutes the first time. Leave this window open.
echo.

rem ------------------------------------------------------------------
rem  1. Python - used only to build; the finished installer needs none
rem ------------------------------------------------------------------
echo [1/5] Looking for Python...
set "PYEXE="
call :findpy
if defined PYEXE goto have_py
echo       Python not found - installing Python 3.11 with winget...
winget install -e --id Python.Python.3.11 --scope user --silent --accept-package-agreements --accept-source-agreements
call :findpy
if defined PYEXE goto have_py
echo.
echo   Could not install Python automatically.
echo   Please install Python 3.11 from https://www.python.org/downloads/
echo   then double-click build_installer.bat again.
goto fail
:have_py
echo       Using %PYEXE%

rem ------------------------------------------------------------------
rem  2. A private copy of the libraries RootsVoice uses
rem ------------------------------------------------------------------
echo.
echo [2/5] Installing the libraries RootsVoice needs...
set "VPY=%ROOT%build\venv\Scripts\python.exe"
if not exist "%VPY%" %PYEXE% -m venv "%ROOT%build\venv"
if not exist "%VPY%" goto fail_venv
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r "%ROOT%requirements.txt" pyinstaller
if errorlevel 1 goto fail_pip

rem ------------------------------------------------------------------
rem  3. The speech model, so RootsVoice works offline after installing
rem ------------------------------------------------------------------
echo.
echo [3/5] Downloading the speech model to include in the installer...
set "ISSDEFS="
if not exist "%ROOT%build\models\base.en\model.bin" "%VPY%" "%ROOT%rootsvoice.py" --download-model base.en "%ROOT%build\models"
if not exist "%ROOT%build\models\base.en\model.bin" set "ISSDEFS=/DNOMODEL"
if defined ISSDEFS echo       Model download failed - building without it. RootsVoice will download it on first use.
if not defined ISSDEFS echo       Speech model ready.

rem ------------------------------------------------------------------
rem  4. Pack RootsVoice and everything it needs into RootsVoice.exe
rem ------------------------------------------------------------------
echo.
echo [4/5] Packing RootsVoice into RootsVoice.exe - this takes a few minutes...
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --onedir --name RootsVoice ^
  --icon "%ROOT%assets\roots.ico" ^
  --version-file "%ROOT%installer\version_info.txt" ^
  --distpath "%ROOT%build\pyinstaller\dist" ^
  --workpath "%ROOT%build\pyinstaller\work" ^
  --specpath "%ROOT%build\pyinstaller" ^
  --collect-all faster_whisper ^
  --collect-all ctranslate2 ^
  --collect-all onnxruntime ^
  --collect-all av ^
  --collect-all tokenizers ^
  --collect-all _sounddevice_data ^
  --hidden-import pygetwindow ^
  --hidden-import pyautogui ^
  "%ROOT%rootsvoice.py"
if errorlevel 1 goto fail
if not exist "%ROOT%build\pyinstaller\dist\RootsVoice\RootsVoice.exe" goto fail

rem ------------------------------------------------------------------
rem  5. The installer wizard (Inno Setup)
rem ------------------------------------------------------------------
echo.
echo [5/5] Building the installer wizard...
set "ISCC="
call :findiscc
if defined ISCC goto have_iscc
echo       Installing Inno Setup with winget...
winget install -e --id JRSoftware.InnoSetup --silent --accept-package-agreements --accept-source-agreements
call :findiscc
if defined ISCC goto have_iscc
echo.
echo   Could not install Inno Setup automatically.
echo   Please install it from https://jrsoftware.org/isdl.php
echo   then double-click build_installer.bat again.
goto fail
:have_iscc
"%ISCC%" %ISSDEFS% "%ROOT%installer\RootsVoice.iss"
if errorlevel 1 goto fail
if not exist "%ROOT%dist\RootsVoice-Setup-2.1.exe" goto fail

echo.
echo  ============================================================
echo    Done! Your installer is ready:
echo    %ROOT%dist\RootsVoice-Setup-2.1.exe
echo.
echo    Copy it to any Windows 10 or 11 PC and double-click it.
echo    Nothing else needs to be installed on that PC.
echo  ============================================================
echo.
explorer "%ROOT%dist"
pause
exit /b 0

:fail_venv
echo.
echo   Could not create the build environment with %PYEXE%.
goto fail

:fail_pip
echo.
echo   Installing the libraries failed. Check the internet connection.
goto fail

:fail
echo.
echo   Something went wrong - scroll up to see the message.
echo   Fix it and double-click build_installer.bat again;
echo   steps that already finished are skipped.
echo.
pause
exit /b 1

rem ------------------------------------------------------------------
:findpy
for %%V in (3.12 3.11 3.10) do if not defined PYEXE py -%%V -c "import sys" >nul 2>&1 && set "PYEXE=py -%%V"
if defined PYEXE exit /b 0
for %%P in ("%LocalAppData%\Programs\Python\Python312\python.exe" "%LocalAppData%\Programs\Python\Python311\python.exe" "%ProgramFiles%\Python312\python.exe" "%ProgramFiles%\Python311\python.exe") do if not defined PYEXE if exist %%P set "PYEXE="%%~P""
exit /b 0

:findiscc
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
exit /b 0
