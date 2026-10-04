@echo off
rem Starts mcIRC - double-click this file.  It finds Python, installs the packages on the first start, and opens mcIRC without a console window.
rem (Run_GUI.bat --make-shortcut puts an mcIRC shortcut with the logo on your Desktop.)
if not exist "%~dp0scripts\start_mcirc.ps1" goto plain
start "" powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0scripts\start_mcirc.ps1" %*
goto :eof
:plain
rem scripts\ is missing (an older update did not deliver it): start the old way; mcIRC restores the missing files itself on its next start
cd /d "%~dp0"
where pythonw >nul 2>&1
if %errorlevel%==0 (start "" pythonw mcIRC.py %*) else (start "" /min python mcIRC.py %*)
