@echo off
chcp 65001 >nul
title jobfinderdz - live service
cd /d "%~dp0"

echo ============================================================
echo   jobfinderdz - LIVE SERVICE
echo   - Telegram bot answers NOW (wizard, commands)
echo   - full scrape starting immediately (Emploitic + ministries)
echo   - automatic refresh every day at 06:00
echo   - every message/button tap is printed below
echo.
echo   CLOSE THIS WINDOW = stop the bot and all work
echo ============================================================
echo.

set PYTHONUNBUFFERED=1
python -m layajobs bot --with-daily --scrape-now --pages 20
echo.
echo bot stopped (window closed or Ctrl+C). Press a key to exit.
pause >nul
