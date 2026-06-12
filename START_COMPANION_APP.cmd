@echo off
cd /d "%~dp0"
echo Starting Companion V1...
echo.
echo The app will be available at:
echo http://127.0.0.1:8000
echo.
echo Keep this window open while using the app.
echo Close this window or press Ctrl+C to stop it.
echo.
start "" "http://127.0.0.1:8000"
call "%~dp0run_companion_v1.cmd"
