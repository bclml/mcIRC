@echo off
rem Starts mcIRC - double-click this file.  It finds Python, installs the packages on the first start, and opens mcIRC without a console window.
rem (Run_GUI.bat --make-shortcut puts an mcIRC shortcut with the logo on your Desktop.)
start "" powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0scripts\start_mcirc.ps1" %*
