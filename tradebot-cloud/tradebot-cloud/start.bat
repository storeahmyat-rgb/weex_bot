@echo off
title TradeBot Cloud
echo.
echo  TradeBot Cloud - Starting...
echo.

cd /d "%~dp0"

taskkill /F /IM python.exe >nul 2>&1

echo  Server start ho raha hai...
start /b python app.py > nul 2>&1

echo  Browser khul raha hai...
timeout /t 3 /nobreak >nul
start http://127.0.0.1:5000

echo.
echo  TradeBot Cloud chal raha hai!
echo  Browser mein khul gaya hoga.
echo  Band karne ke liye is window ko band karo.
echo.
pause
