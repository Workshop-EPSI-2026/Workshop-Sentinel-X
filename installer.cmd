@echo off
rem Sentinel-X : installe tout le projet sur ce poste Windows (a lancer une fois apres le clone).
rem Le meme pour tout le monde. Option : installer.cmd -SkipSoftware (logiciels deja installes).
rem Ensuite : verifier-serveur.cmd dit si ce poste peut etre le serveur de la demo.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup-poste.ps1" %*
echo.
pause
