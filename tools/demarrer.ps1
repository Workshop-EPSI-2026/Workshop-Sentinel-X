<#
.SYNOPSIS
  Sentinel-X : demarre tout sur le PC serveur (stack Docker + vision sur la webcam), en une commande.

.DESCRIPTION
  Depuis la racine du depot, PowerShell normal (pas besoin d'administrateur) :

    powershell -ExecutionPolicy Bypass -File tools\demarrer.ps1                 # stack + vision sur la webcam 0
    powershell -ExecutionPolicy Bypass -File tools\demarrer.ps1 -Source ai\vision\data\demo.mp4   # plan B
    powershell -ExecutionPolicy Bypass -File tools\demarrer.ps1 -SansVision     # stack seule
    powershell -ExecutionPolicy Bypass -File tools\demarrer.ps1 -Arreter        # arrete tout (donnees conservees)

  Prealables : infra\.env rempli, infra\mosquitto\passwd cree (infra\mosquitto\README.md),
  .venv avec la vision (installer.cmd), certificats de Lisa des le passage en TLS.
#>
param(
  [string]$Source,
  [switch]$SansVision,
  [switch]$Arreter
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "   $msg" -ForegroundColor Red; exit 1 }

function Stop-Vision {
  Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like '*-m app.main*' -and $_.CommandLine -like '*infra*.env*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "   vision arretee (processus $($_.ProcessId))" }
}

if ($Arreter) {
  Step "Arret"
  Stop-Vision
  Push-Location infra; docker compose stop; Pop-Location
  exit 0
}

# ------------------------------------------------------------------ 1. prealables
Step "1/4 Prealables"
if (-not (Test-Path infra\.env)) { Fail "infra\.env absent : python tools\configurer.py (cree .env et les comptes MQTT)" }
if (Select-String -Path infra\.env -Pattern 'CHANGE_ME' -Quiet) { Fail "infra\.env contient encore des CHANGE_ME" }
if (-not (Test-Path infra\mosquitto\passwd)) { Fail "infra\mosquitto\passwd absent : python tools\configurer.py" }
$envs = @{}
Get-Content infra\.env | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object {
  $k, $v = $_ -split '=', 2; $envs[$k.Trim()] = ($v -split ' #')[0].Trim()
}
if ($envs['MQTT_TLS'] -eq 'true' -and -not (Test-Path security\certs\ca.crt)) {
  Fail "MQTT_TLS=true mais security\certs\ca.crt absent : certificats de Lisa (security\README.md)"
}
Write-Host "   profils : '$($envs['COMPOSE_PROFILES'])' · MQTT $($envs['MQTT_PORT']) TLS=$($envs['MQTT_TLS'])"

# ------------------------------------------------------------------ 2. Docker Desktop
Step "2/4 Docker Desktop"
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  $exe = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
  if (-not (Test-Path $exe)) { Fail "Docker Desktop introuvable : winget install --id Docker.DockerDesktop -e" }
  Start-Process $exe
  Write-Host "   demarrage de Docker Desktop" -NoNewline
  for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep 3; Write-Host "." -NoNewline
    docker info *> $null; if ($LASTEXITCODE -eq 0) { break }
  }
  Write-Host ""
  if ($LASTEXITCODE -ne 0) { Fail "Docker Desktop ne repond pas apres 3 minutes" }
}
Write-Host "   Docker pret"

# ------------------------------------------------------------------ 3. stack
Step "3/4 Stack (docker compose)"
Push-Location infra
docker compose up -d --build
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Fail "docker compose a echoue (voir ci-dessus)" }
Start-Sleep 5
Push-Location infra; docker compose ps --format "table {{.Name}}\t{{.Status}}"; Pop-Location

# ------------------------------------------------------------------ 4. vision
if (-not $SansVision) {
  Step "4/4 Vision (webcam, hors Docker)"
  Stop-Vision
  $py = Join-Path $Root '.venv\Scripts\python.exe'
  if (-not (Test-Path $py)) { Fail ".venv absent : lancer installer.cmd" }
  & $py -c "import ultralytics, cv2" 2>$null
  if ($LASTEXITCODE -ne 0) { Fail "dependances vision absentes : relancer installer.cmd" }
  $src = if ($Source) { (Resolve-Path $Source).Path } elseif ($envs['VISION_SOURCE']) { $envs['VISION_SOURCE'] } else { '0' }
  $model = if ($envs['VISION_MODEL']) { $envs['VISION_MODEL'] } else { 'yolov8n.pt' }
  $cmd = "Set-Location '$Root\ai\vision'; `$host.UI.RawUI.WindowTitle = 'Sentinel-X vision'; " +
         "& '$py' -m app.main --env '$Root\infra\.env' --source '$src' --model '$model'"
  Start-Process powershell.exe -ArgumentList '-NoExit', '-Command', $cmd -WindowStyle Minimized
  Write-Host "   vision lancee dans une fenetre reduite (source $src, modele $model)"
  Start-Sleep 8
  try {
    $h = Invoke-RestMethod -Uri http://127.0.0.1:8001/health -TimeoutSec 5
    Write-Host "   vision : $($h.status), $($h.fps) images/s"
  } catch { Write-Host "   vision pas encore prete (premier lancement : telechargement du modele)" -ForegroundColor Yellow }
}

Write-Host "`nSentinel-X demarre." -ForegroundColor Green
if ($envs['COMPOSE_PROFILES'] -match 'app') {
  Write-Host "Dashboard : https://localhost  (depuis le reseau du point d'acces : https://192.168.137.1)"
  Start-Process "https://localhost"
}
if (-not $SansVision) { Write-Host "Video annotee : http://127.0.0.1:8001/video" }
if ($envs['COMPOSE_PROFILES'] -match 'ai') { Write-Host "Sentinel Brain en direct : docker logs -f snx-anomaly" }
Write-Host "Messages MQTT en direct : docker exec snx-mosquitto mosquitto_sub -h localhost -p 1883 -u monitor -P <mot de passe monitor> -t 'sentinel/#' -v"
Write-Host "   (mot de passe : python tools\configurer.py --afficher)"
Write-Host "Boitier simule : python tools\simulator.py --scenario all   (vrai boitier : firmware\sentinel_esp)"
Write-Host "Arret : powershell -ExecutionPolicy Bypass -File tools\demarrer.ps1 -Arreter"
