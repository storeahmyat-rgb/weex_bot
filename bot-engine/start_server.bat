@echo off
REM ============================================================
REM  Start License Server + Ngrok Tunnel (Admin)
REM  Run this on admin's laptop to start the SaaS license server
REM ============================================================
cd /d "%~dp0"

echo ============================================================
echo  License Server Starting (SaaS Mode)
echo ============================================================
echo.

REM Step 1: Start Flask license server in background
echo [1/2] License server start ho raha hai (port 5001)...
start /b python license_server.py

REM Wait for server to start
timeout /t 3 /nobreak >nul

REM Step 2: Start ngrok tunnel
echo [2/2] Ngrok tunnel start ho raha hai...
echo.

REM Check if ngrok is installed
where ngrok >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Ngrok install nahi hai.
    echo Download: https://ngrok.com/download
    echo.
    echo Alternative: Cloudflare Tunnel use karo
    echo   cloudflared tunnel --url http://localhost:5001
    echo.
    echo Abhi ke liye server localhost pe chal raha hai.
    echo Admin panel: http://localhost:5001/admin
    echo.
    pause
    exit /b 0
)

REM Start ngrok
echo ============================================================
echo  Server Live Ho Gaya!
echo ============================================================
echo.
echo  Admin Panel: http://localhost:5001/admin
echo  Ngrok URL: niche check karo
echo.
echo  Customer .exe mein ngrok URL daalna hai
echo  (bot/license_client.py mein LICENSE_SERVER_URL)
echo.
echo  Press Ctrl+C to stop
echo ============================================================
echo.

ngrok http 5001

REM Keep window open
pause
