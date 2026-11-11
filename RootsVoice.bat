@echo off
rem Starts RootsVoice with its own Python environment (made by setup_rootsvoice.bat).
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" goto run
echo RootsVoice isn't set up on this computer yet - running setup first...
rem setup starts RootsVoice itself when it finishes
call "%~dp0setup_rootsvoice.bat"
exit /b
:run
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0rootsvoice.py"
