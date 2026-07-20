@echo off
REM ============================================================
REM  Binance Futures Bot - .exe Builder Script (DEBUG VERSION)
REM  Run this on Windows to create BinanceFuturesBot.exe
REM  This version keeps console open on crash so you can see errors
REM ============================================================
cd /d "%~dp0"

echo ============================================================
echo  Binance Futures Bot - Building .exe (Debug Version)
echo ============================================================
echo.

REM Step 1: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python install nahi hai. Pehle Python 3.9+ install karo.
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Step 2: Install build dependencies
echo [1/4] Build dependencies install ho rahe hain...
pip install pyinstaller pyarmor --upgrade --quiet
if errorlevel 1 (
    echo [ERROR] PyInstaller install nahi hua.
    pause
    exit /b 1
)

REM Step 3: Install app dependencies
echo [2/4] App dependencies install ho rahe hain...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] requirements.txt install fail.
    pause
    exit /b 1
)

REM Step 4: Build .exe with PyInstaller (NO obfuscation for debug)
echo [3/4] .exe build ho rahi hai (5-10 minutes lag sakte hain)...
echo [INFO] Skipping PyArmor obfuscation for debug build
echo [INFO] Console will stay open if crash happens

pyinstaller binance_bot.spec --noconfirm --clean
if errorlevel 1 (
    echo [ERROR] .exe build fail ho gaya.
    pause
    exit /b 1
)

REM Step 5: Cleanup
echo [4/4] Cleanup ho rahi hai...
if exist build rmdir /S /Q build

echo.
echo ============================================================
echo  ✅ BUILD SUCCESSFUL!
echo ============================================================
echo.
echo  .exe location: dist\BinanceFuturesBot.exe
echo.
echo  IMPORTANT:
echo  - Agar .exe crash ho, to crash.log file banegi
echo  - Console open rahega jab tak Enter na dabao
echo  - Crash log mujhe bhejo taake main fix kar sakun
echo.
echo  Test karne ke liye:
echo  1. dist\BinanceFuturesBot.exe chalao
echo  2. Agar error aaye, crash.log file bhejo
echo  3. Browser: http://localhost:5000
echo.
pause
