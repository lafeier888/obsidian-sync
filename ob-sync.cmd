@echo off
setlocal
if "%~1"=="" goto usage
if defined PYTHON_BIN goto custom
where py >nul 2>nul
if not errorlevel 1 goto launcher
where python >nul 2>nul
if not errorlevel 1 goto python
 echo Python 3.10+ is required. Install Python and add it to PATH.
exit /b 1
:custom
"%PYTHON_BIN%" "%~dp0service_control.py" %*
exit /b %errorlevel%
:launcher
py -3 "%~dp0service_control.py" %*
exit /b %errorlevel%
:python
python "%~dp0service_control.py" %*
exit /b %errorlevel%
:usage
echo Usage: ob-sync.cmd start^|stop^|restart^|status [--port 8899] [--host 127.0.0.1]
exit /b 0
