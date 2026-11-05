@echo off
cd /d "%~dp0"
py -3.13 -m kgstv gui
if errorlevel 1 pause
