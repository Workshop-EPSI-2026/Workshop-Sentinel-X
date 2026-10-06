# Lance le service vision directement sur le PC serveur Windows.
# Docker Desktop n'accède pas à la webcam : la vision tourne hors Docker et parle à l'API
# par nginx (https://localhost), comme un client. nginx lui renvoie /video (host.docker.internal:8001).
#
# Usage, depuis la racine du dépôt (Python 3.12 installé, stack lancée avec COMPOSE_PROFILES=app,ai) :
#   powershell -ExecutionPolicy Bypass -File ai\vision\run-windows.ps1

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

# Valeurs lues dans infra/.env (même source que la stack Docker)
$envFile = Join-Path $root 'infra\.env'
if (-not (Test-Path $envFile)) { throw "infra\.env introuvable : copier infra\.env.example puis le remplir." }
$cfg = @{}
foreach ($line in Get-Content $envFile) {
  if ($line -match '^\s*([A-Z_]+)\s*=\s*(.*?)\s*(#.*)?$') { $cfg[$Matches[1]] = $Matches[2] }
}
function Get-Cfg($name, $default) { if ($cfg[$name]) { $cfg[$name] } else { $default } }

# Environnement Python dédié (ignoré par Git), créé au premier lancement
$venv = Join-Path $PSScriptRoot '.venv'
$python = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $python)) {
  py -3.12 -m venv $venv
  & $python -m pip install --upgrade pip
  & $python -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
}

$env:API_URL       = 'https://localhost'
$env:API_CA        = Join-Path $root 'security\certs\ca.crt'   # vérification TLS de nginx
$env:API_KEY       = Get-Cfg 'API_KEY' ''
$env:CAMERA_DEVICE = Get-Cfg 'VISION_CAMERA' '0'               # index OpenCV de la webcam
$env:MODEL_PATH    = Join-Path $root ('ai\vision\models\' + (Get-Cfg 'VISION_MODEL' 'yolov8n_ncnn_model'))
$env:SITE_PROFILE  = Join-Path $root ('config\' + (Get-Cfg 'SITE_PROFILE_FILE' 'site.example.yml'))

# Écoute locale uniquement : 8001 n'est jamais exposé au réseau de table
Push-Location $PSScriptRoot
try {
  & $python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
} finally {
  Pop-Location
}
