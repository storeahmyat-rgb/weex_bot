@echo off
REM ============================================
REM TradeBot SaaS - Windows Launcher
REM ============================================
REM Yeh file bot ko start karti hai.
REM Pehli baar install ke liye: install_windows.bat chalao.
REM ============================================

cd /d "%~dp0"

echo ================================
echo  TradeBot SaaS - Starting
echo ================================

REM Activate venv if exists
if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
)

REM Check dependencies
python -c "import flask, flask_socketio, pandas, numpy" 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
)

REM Load admin password from file (if exists)
if exist ".admin_password.txt" (
    for /f "delims=" %%a in (.admin_password.txt) do set "ADMIN_SECRET=%%a"
)

REM Start the bot
echo.
echo Bot URL:        http://localhost:5000
echo Admin Panel:    http://localhost:5000/admin
if defined ADMIN_SECRET (
    echo Admin Password: %ADMIN_SECRET%
) else (
    echo Admin Password: AdminBot@2024! ^(default^)
)
echo.
echo Press Ctrl+C to stop
echo ================================
echo.

REM Open browser after 3 seconds
timeout /t 3 /nobreak >nul
start http://localhost:5000

python app.py

pause
