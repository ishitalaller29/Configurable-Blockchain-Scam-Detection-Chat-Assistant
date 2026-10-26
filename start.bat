@echo off
setlocal
title Scam Detection Chat Assistant
cd /d "%~dp0"

set "URL=http://localhost:8000"
set "DOCKER_DESKTOP=C:\Program Files\Docker\Docker\Docker Desktop.exe"

echo.
echo  Starting the Scam Detection Chat Assistant...
echo.

rem --- 1. Make sure Docker is running (start Docker Desktop if it isn't) ---
docker info >nul 2>&1
if not errorlevel 1 goto docker_ready

if exist "%DOCKER_DESKTOP%" (
    echo  Docker Desktop is not running. Starting it now...
    start "" "%DOCKER_DESKTOP%"
) else (
    echo  Docker is not running and Docker Desktop was not found.
    echo  Please install or start Docker Desktop, then run this again.
    pause
    exit /b 1
)

set /a TRIES=0
:wait_docker
timeout /t 3 /nobreak >nul
docker info >nul 2>&1
if not errorlevel 1 goto docker_ready
set /a TRIES+=1
if %TRIES% lss 60 goto wait_docker
echo  Docker did not start within 3 minutes. Open Docker Desktop, wait for
echo  "Engine running", then run this again.
pause
exit /b 1

:docker_ready
echo  [1/4] Docker is running.

rem --- 2. Docker Compose needs a .env file, even an empty one ---
if not exist ".env" (
    type nul > ".env"
    echo        No .env found - created an empty one. Add ETHERSCAN_API_KEY=... for full results.
)

rem --- 3. Build and start the containers ---
echo  [2/4] Building and starting containers (first run can take a few minutes)...
docker compose up --build -d
if errorlevel 1 (
    echo  Failed to start the containers. See the messages above.
    pause
    exit /b 1
)

rem --- 4. Make sure the language model is downloaded (first run only) ---
echo  [3/4] Checking the language model...
set /a TRIES=0
:wait_ollama
docker compose exec -T ollama ollama list >nul 2>&1
if not errorlevel 1 goto ollama_ready
set /a TRIES+=1
if %TRIES% geq 30 (
    echo  Ollama did not start. Run: docker compose logs ollama
    pause
    exit /b 1
)
timeout /t 2 /nobreak >nul
goto wait_ollama

:ollama_ready
docker compose exec -T ollama ollama list | findstr /i "llama3.1" >nul
if errorlevel 1 (
    echo        Downloading llama3.1 - this is several GB and only happens once...
    docker compose exec -T ollama ollama pull llama3.1
    if errorlevel 1 (
        echo  Model download failed. Check your internet connection and run this again.
        pause
        exit /b 1
    )
)

rem --- 5. Wait for the website to answer, then open it ---
echo  [4/4] Waiting for the website...
powershell -NoProfile -Command "for($i=0;$i -lt 60;$i++){ try { Invoke-WebRequest '%URL%' -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { Start-Sleep -Seconds 2 } }; exit 1"
if errorlevel 1 (
    echo  The website did not respond. Run: docker compose logs bot
    pause
    exit /b 1
)

echo.
echo  ==========================================================
echo    Assistant is ready: %URL%
echo  ==========================================================
echo.
echo  Opening it in your browser. To shut everything down, run stop.bat.
start "" "%URL%"
timeout /t 10
exit /b 0
