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
  [switch]$SansNotifications,
  [switch]$Arreter
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "   $msg" -ForegroundColor Red; exit 1 }

function Stop-Services {
  # vision et notifications : processus python lances par ce script (« -m app.main --env ...infra\.env »)
  Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like '*-m app.main*' -and $_.CommandLine -like '*infra*.env*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "   service PC arrete (processus $($_.ProcessId))" }
}

function Start-PcService($name, $dir, $extra) {
  $py = Join-Path $Root '.venv\Scripts\python.exe'
  $cmd = "Set-Location '$Root\$dir'; `$host.UI.RawUI.WindowTitle = 'Sentinel-X $name'; " +
         "& '$py' -m app.main --env '$Root\infra\.env' $extra"
  Start-Process powershell.exe -ArgumentList '-NoExit', '-Command', $cmd -WindowStyle Minimized
}

if ($Arreter) {
  Step "Arret"
  Stop-Services
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
Write-Host "   profils : '$($envs['COMPOSE_PROFILES'])' - MQTT $($envs['MQTT_PORT']) TLS=$($envs['MQTT_TLS'])"
if ($envs['MQTT_TLS'] -ne 'true') {
  Write-Host "   [!!] MQTT EN CLAIR (mode socle, port 1883) : reserve a la mise au point du boitier." -ForegroundColor Yellow
  Write-Host "        Avant la demo : python tools\configurer.py --mode tls (firmware en TLS sur 8883)" -ForegroundColor Yellow
}

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

# Ports publies par Sentinel-X : libres, ou deja tenus par nos propres conteneurs (snx-*)
$ports = @(443) + $(if ($envs['MQTT_TLS'] -eq 'true') { 8883 } else { 1883 })
foreach ($p in $ports) {
  $others = @(docker ps --filter "publish=$p" --format '{{.Names}}' | Where-Object { $_ -and $_ -notlike 'snx-*' })
  if ($others.Count) { Fail "port $p deja pris par le conteneur $($others -join ', ') : docker stop $($others -join ' ') puis relancer" }
  $l = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($l) {
    $proc = (Get-Process -Id $l.OwningProcess -ErrorAction SilentlyContinue).ProcessName
    if ($proc -and $proc -notmatch '^(com\.docker|docker|wslrelay|vpnkit)') {
      Fail "port $p deja pris par le programme $proc (PID $($l.OwningProcess)) : le fermer puis relancer"
    }
  }
}
Write-Host "   ports libres : $($ports -join ', ')"

# ------------------------------------------------------------------ 3. stack
# Dashboard recompile s'il manque ou si ses sources sont plus recentes (mise a jour du depot)
$dist = 'dashboard\dist\index.html'
$stale = -not (Test-Path $dist)
if (-not $stale) {
  $built = (Get-Item $dist).LastWriteTime
  $stale = [bool](Get-ChildItem dashboard\src, dashboard\index.html, dashboard\package-lock.json -Recurse -File |
    Where-Object { $_.LastWriteTime -gt $built } | Select-Object -First 1)
}
if ($envs['COMPOSE_PROFILES'] -match 'app' -and $stale) {
  Step "Dashboard : compilation"
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Fail "Node.js absent : installer.cmd, ou winget install OpenJS.NodeJS.LTS" }
  Push-Location dashboard
  npm ci --no-audit --no-fund
  if ($LASTEXITCODE -eq 0) { npm run build }
  $code = $LASTEXITCODE
  Pop-Location
  if ($code -ne 0) { Fail "compilation du dashboard impossible (voir ci-dessus)" }
}
Step "3/4 Stack (docker compose)"
Push-Location infra
docker compose up -d --build
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Fail "docker compose a echoue (voir ci-dessus)" }
docker kill -s HUP snx-mosquitto *> $null   # relit comptes (passwd) et droits (aclfile) sans couper les clients
Start-Sleep 5
Write-Host "   verification de sante des conteneurs" -NoNewline
for ($i = 0; $i -lt 30; $i++) {
  $st = @(docker ps -a --filter "name=snx-" --format '{{.Names}} {{.Status}}')
  if (-not ($st -match 'starting')) { break }
  Start-Sleep 3; Write-Host "." -NoNewline
}
Write-Host ""
$bad = @($st | Where-Object { $_ -match 'unhealthy|Restarting|Exited' })
foreach ($b in $st) {
  if ($bad -contains $b) { Write-Host "   [KO] $b   ->  docker logs $(($b -split ' ')[0]) --tail 30" -ForegroundColor Red }
  else { Write-Host "   [OK] $b" }
}
if ($bad.Count) { Write-Host "   Des conteneurs sont en panne : voir leurs journaux ci-dessus avant la demo." -ForegroundColor Red }

# ------------------------------------------------------------------ 4. vision
Stop-Services   # vision et notifications d'un lancement precedent
if (-not $SansVision) {
  Step "4/4 Vision (webcam, hors Docker)"
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

# ------------------------------------------------------------------ 5. notifications (haut-parleurs et mails : sur le PC)
if (-not $SansNotifications) {
  Step "Notifications (voix, mails)"
  Start-PcService 'notifications' 'ai\notify' ''
  if ($envs['SMTP_HOST']) { Write-Host "   annonces vocales et mails vers $($envs['NOTIFY_TO'])" }
  else { Write-Host "   annonces vocales actives ; mails : remplir SMTP_* et NOTIFY_TO dans infra\.env" -ForegroundColor Yellow }
  Write-Host "   essai : cd ai\notify ; ..\..\.venv\Scripts\python.exe -m app.main --env ..\..\infra\.env --tester"
}

Write-Host "`nSentinel-X demarre." -ForegroundColor Green
if ($envs['COMPOSE_PROFILES'] -match 'app') {
  Write-Host "Dashboard : https://localhost  (depuis le reseau du point d'acces : https://192.168.137.1)"
  Write-Host "   jeton operateur pour se connecter : python tools\configurer.py --afficher"
  Start-Process "https://localhost"
}
if (-not $SansVision) { Write-Host "Video annotee : http://127.0.0.1:8001/video" }
if ($envs['COMPOSE_PROFILES'] -match 'ai') { Write-Host "Sentinel Brain en direct : docker logs -f snx-anomaly" }
Write-Host "Messages MQTT en direct : docker exec snx-mosquitto mosquitto_sub -h localhost -p 1883 -u monitor -P <mot de passe monitor> -t 'sentinel/#' -v"
Write-Host "   (mot de passe : python tools\configurer.py --afficher)"
Write-Host "Boitier simule : python tools\simulator.py --scenario all   (vrai boitier : firmware\sentinel_esp)"
Write-Host "Arret : powershell -ExecutionPolicy Bypass -File tools\demarrer.ps1 -Arreter"
