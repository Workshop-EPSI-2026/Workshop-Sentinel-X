@echo off
rem Sentinel-X : demonstration sur ce PC, sans Docker, sans broker, sans configuration.
rem   demo.cmd          vision sur la video de demonstration + Sentinel Brain sur le simulateur
rem   demo.cmd webcam   vision sur votre webcam
rem A lancer apres installer.cmd.
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo .venv absent : lancer d'abord installer.cmd
  pause
  exit /b 1
)
set "SRC=data\demo.mp4"
if /i "%~1"=="webcam" set "SRC=0"

if not exist "ai\vision\data\demo.mp4" (
  echo Creation de la video de demonstration...
  "%PY%" ai\vision\tools\demo_video.py
)

echo Lancement de la vision dans une fenetre reduite "Sentinel-X vision"...
start "Sentinel-X vision" /min /d "%~dp0ai\vision" "%PY%" -m app.main --no-mqtt --source %SRC%
timeout /t 12 /nobreak >nul
start "" "http://127.0.0.1:8001/video"

echo.
echo  VISION : http://127.0.0.1:8001/video (ouvert dans le navigateur)
echo           cadres autour des personnes, zone interdite, badges, camera masquee ou sombre.
echo  BRAIN  : rejoue ci-dessous les scenarios du boitier (environ 2 minutes).
echo.
"%PY%" tools\demo_brain.py

echo.
echo Appuyez sur une touche pour arreter la vision et fermer la demonstration.
pause >nul
taskkill /fi "WINDOWTITLE eq Sentinel-X vision*" /t /f >nul 2>&1
endlocal
