@echo off
title Scam Detection Chat Assistant
cd /d "%~dp0"
echo  Stopping the Scam Detection Chat Assistant...
docker compose down
echo  Stopped. (The downloaded language model is kept for next time.)
timeout /t 5
