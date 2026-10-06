<#
.SYNOPSIS
  Sentinel-X : installe sur un poste Windows exactement le meme environnement que le reste de l'equipe.

.DESCRIPTION
  A lancer depuis la racine du depot clone, dans PowerShell (pas besoin d'etre administrateur :
  Windows demandera l'autorisation pour chaque logiciel si necessaire).

    powershell -ExecutionPolicy Bypass -File tools\setup-poste.ps1 -Role ia

  Roles : commun, ia (Jeffrick), iot (Momo, Michel), cyber (Lisa), integration (Constantin), fablab (Michel),
         serveur (le PC qui fait tourner Sentinel-X le jour de la demo : Docker + vision + modele YOLO).
  Le script peut etre relance sans risque : ce qui est deja installe est conserve.

  Etapes :
    1. Logiciels (winget)         Git, GitHub CLI, VS Code, Python 3.12, nvm, Docker Desktop, outils du role
    2. Node.js                    version de .nvmrc, via nvm
    3. Extensions VS Code         celles de .vscode/extensions.json
    4. Git                        autocrlf=false, branche main, identite
    5. Cle SSH                    ed25519 pour GitHub
    6. Python                     .venv avec Python de .python-version et versions exactes (requirements-dev.txt)
    7. Controle                   tools\doctor.py
#>
param(
  [ValidateSet('commun', 'ia', 'iot', 'cyber', 'integration', 'fablab', 'serveur')]
  [string]$Role = 'commun',
  [switch]$SkipSoftware
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Info($msg) { Write-Host "   $msg" }
function Warn($msg) { Write-Host "   ATTENTION : $msg" -ForegroundColor Yellow }

function Update-SessionPath {
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
              [Environment]::GetEnvironmentVariable('Path', 'User')
  foreach ($extra in @("$env:ProgramFiles\mosquitto", "$env:ProgramFiles\Git\usr\bin", "$env:APPDATA\nvm",
                       "$env:ProgramFiles\nodejs")) {
    if ((Test-Path $extra) -and ($env:Path -notlike "*$extra*")) { $env:Path += ";$extra" }
  }
}

function Install-Package([string]$Id, [string]$Label) {
  $present = winget list --id $Id -e --accept-source-agreements 2>$null | Select-String -SimpleMatch $Id
  if ($present) { Info "$Label : deja installe"; return }
  Info "$Label : installation..."
  winget install --id $Id -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
  if ($LASTEXITCODE -ne 0) { Warn "$Label n'a pas pu etre installe automatiquement (code $LASTEXITCODE)." }
}

if (-not (Test-Path "$Root\.python-version") -or -not (Test-Path "$Root\requirements-dev.txt")) {
  throw "Lancer ce script depuis le depot Workshop-Sentinel-X clone (fichiers de versions introuvables)."
}
$PyVersion = (Get-Content "$Root\.python-version" -Raw).Trim()
$NodeVersion = (Get-Content "$Root\.nvmrc" -Raw).Trim()
Write-Host "Sentinel-X : installation du poste, role '$Role' (Python $PyVersion, Node $NodeVersion)" -ForegroundColor Green

# ------------------------------------------------------------------ 1. Logiciels
if (-not $SkipSoftware) {
  Step "1/7 Logiciels"
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget introuvable : installer 'App Installer' depuis le Microsoft Store, puis relancer."
  }
  $common = [ordered]@{
    'Git.Git'                    = 'Git'
    'GitHub.cli'                 = 'GitHub CLI'
    'Microsoft.VisualStudioCode' = 'VS Code'
    "Python.Python.$PyVersion"   = "Python $PyVersion"
    'CoreyButler.NVMforWindows'  = 'nvm (Node.js)'
    'Docker.DockerDesktop'       = 'Docker Desktop'
  }
  foreach ($k in $common.Keys) { Install-Package $k $common[$k] }
  switch ($Role) {
    'cyber'       { Install-Package 'Insecure.Nmap' 'Nmap'; Install-Package 'WiresharkFoundation.Wireshark' 'Wireshark' }
    'fablab'      { Info "Fusion 360 : licence etudiante sur autodesk.com (pas d'installation automatique)" }
    'integration' { Install-Package 'OBSProject.OBSStudio' 'OBS Studio' }
  }
  Update-SessionPath
  if (-not (Get-Command mosquitto_sub -ErrorAction SilentlyContinue)) {
    Warn "Clients Mosquitto absents : installer depuis https://mosquitto.org/download/ (Windows 64 bits),"
    Warn "puis ajouter C:\Program Files\mosquitto au Path et relancer ce script."
  }
}
Update-SessionPath

# ------------------------------------------------------------------ 2. Node.js
Step "2/7 Node.js $NodeVersion"
if (Get-Command nvm -ErrorAction SilentlyContinue) {
  nvm install $NodeVersion | Out-Null
  nvm use $NodeVersion | Out-Null
  if ($LASTEXITCODE -ne 0) { Warn "'nvm use' demande souvent les droits administrateur : relancer 'nvm use $NodeVersion' dans un PowerShell administrateur." }
  Update-SessionPath
  if (Get-Command node -ErrorAction SilentlyContinue) { Info "node $(node --version)" }
} else {
  Warn "nvm introuvable : fermer et rouvrir PowerShell apres l'etape 1, puis relancer le script."
}

# ------------------------------------------------------------------ 3. Extensions VS Code
Step "3/7 Extensions VS Code"
if (Get-Command code -ErrorAction SilentlyContinue) {
  $wanted = (Get-Content "$Root\.vscode\extensions.json" -Raw | ConvertFrom-Json).recommendations
  if ($Role -ne 'iot') { $wanted = $wanted | Where-Object { $_ -ne 'platformio.platformio-ide' } }
  $have = code --list-extensions
  foreach ($ext in $wanted) {
    if ($have -contains $ext) { Info "$ext : deja installee" }
    else { code --install-extension $ext | Out-Null; Info "$ext : installee" }
  }
} else {
  Warn "Commande 'code' introuvable : rouvrir PowerShell apres l'installation de VS Code."
}

# ------------------------------------------------------------------ 4. Git
Step "4/7 Git"
git config --global core.autocrlf false
git config --global init.defaultBranch main
git config --global pull.rebase false
if (-not (git config --global user.name)) {
  $name = Read-Host "   Votre prenom et nom (auteur des commits)"
  git config --global user.name "$name"
}
if (-not (git config --global user.email)) {
  $mail = Read-Host "   L'adresse e-mail de votre compte GitHub"
  git config --global user.email "$mail"
}
Info "auteur : $(git config --global user.name) <$(git config --global user.email)>"

# ------------------------------------------------------------------ 5. Cle SSH
Step "5/7 Cle SSH"
$key = Join-Path $HOME '.ssh\id_ed25519'
if (Test-Path "$key.pub") {
  Info "deja presente : $key.pub"
} else {
  New-Item -ItemType Directory -Force -Path (Join-Path $HOME '.ssh') | Out-Null
  ssh-keygen -t ed25519 -C "$env:USERNAME@sentinel" -f $key
  Info "cle publique a ajouter dans GitHub (Settings > SSH and GPG keys) :"
  Get-Content "$key.pub"
}

# ------------------------------------------------------------------ 6. Python
Step "6/7 Environnement Python (.venv, versions exactes)"
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw "Lanceur 'py' introuvable : rouvrir PowerShell apres l'etape 1." }
if (-not (Test-Path "$Root\.venv\Scripts\python.exe")) {
  py "-$PyVersion" -m venv .venv
  Info ".venv cree avec Python $PyVersion"
}
$py = "$Root\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r requirements-dev.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "Installation des dependances Python echouee." }
if ($Role -in 'ia', 'serveur') {
  Info "role $Role : PyTorch CPU et dependances de la vision"
  & $py -m pip install -r ai\vision\torch-cpu.txt --index-url https://download.pytorch.org/whl/cpu --quiet
  & $py -m pip install -r ai\vision\requirements.txt --quiet
  Info "modele YOLOv8n (6 Mo) dans ai\vision\models : a faire avec Internet, la demo s'en passe ensuite"
  & $py -c "from ultralytics import YOLO; YOLO(r'ai\vision\models\yolov8n.pt')"
}
Info "dependances installees"

# ------------------------------------------------------------------ 7. Controle
Step "7/7 Controle du poste"
& $py tools\doctor.py --role $Role
$code = $LASTEXITCODE
Write-Host ""
if ($code -eq 0) {
  Write-Host "Poste conforme. Activer l'environnement a chaque session : .venv\Scripts\activate" -ForegroundColor Green
} else {
  Write-Host "Corriger les lignes [KO] ci-dessus (la commande est indiquee), puis relancer : python tools\doctor.py --role $Role" -ForegroundColor Yellow
}
exit $code
