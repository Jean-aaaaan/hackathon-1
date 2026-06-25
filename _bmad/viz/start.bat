@echo off
cd /d "%~dp0"
if not exist node_modules\ws (
    echo Installing dependencies...
    call npm install
    echo.
)
echo ================================================
echo   BMAD Live Agent Visualization
echo   Starting server on http://localhost:3333
echo   Press Ctrl+C to stop
echo ================================================
echo.
node server.js
