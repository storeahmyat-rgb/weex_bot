@echo off
REM ============================================
REM TradeBot SaaS - One-Click Installer (Windows)
REM ============================================
REM Yeh script sab kuch install karta hai:
REM   - Python check/install
REM   - Bot dependencies
REM   - Bot start
REM
REM Usage: Double-click karo ya command prompt mein run karo
REM ============================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ==========================================
echo   TradeBot SaaS - Windows Installer
echo ==========================================
echo.

REM Check Python
echo [1/4] Python check kar rahe hain...
python --version >nul 2>&1
if errorlevel 1 (
    echo     Python nahi mila. Install kar rahe hain...
    echo.
    echo     Python download karo: https://www.python.org/downloads/
    echo     Install karte time "Add Python to PATH" CHECK karna!
    echo.
    echo     Press any key to open Python download page...
    pause >nul
    start https://www.python.org/downloads/
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo     Python !PYVER! mila
echo.

REM Install dependencies
echo [2/4] Bot dependencies install kar rahe hain...
echo     (Yeh 2-5 minute lag sakta hai, please wait...)
echo.
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo     ERROR: Dependencies install nahi hui
    echo     Try: pip install -r requirements.txt
    pause
    exit /b 1
)
echo     Dependencies installed
echo.

REM Create admin password file (default)
echo [3/4] Admin password set kar rahe hain...
if not exist ".admin_password.txt" (
    echo AdminBot@2024!> .admin_password.txt
    echo     Default admin password: AdminBot@2024!
    echo     (Change karne ke liye .admin_password.txt edit karo)
) else (
    echo     Admin password already set
)
echo.

REM Start bot
echo [4/4] Bot start kar rahe hain...
echo.
echo ==========================================
echo   Installation Complete!
echo ==========================================
echo.
echo   Bot URL: http://localhost:5000
echo   Admin Panel: http://localhost:5000/admin
echo   Admin Password: AdminBot@2024!
echo.
echo   Browser automatically open ho raha hai...
echo.
echo   Bot ko band karne ke liye is window close karo
echo   ya Ctrl+C dabao.
echo ==========================================
echo.

REM Open browser
timeout /t 3 /nobreak >nul
start http://localhost:5000

REM Start bot
python app.py

pause
