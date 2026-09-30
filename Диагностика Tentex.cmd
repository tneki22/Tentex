@echo off
setlocal
chcp 65001 >nul
rem Use Windows PowerShell modules even when launched from PowerShell 7.
set "PSModulePath=%SystemRoot%\System32\WindowsPowerShell\v1.0\Modules"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launcher.ps1" status %*
set "tentex_exit=%ERRORLEVEL%"
pause
exit /b %tentex_exit%
