<#
.SYNOPSIS
  Sentinel-X : installe sur un poste Windows exactement le meme environnement que le reste de l'equipe.

.DESCRIPTION
  A lancer depuis la racine du depot clone, dans PowerShell (pas besoin d'etre administrateur :
  Windows demandera l'autorisation pour chaque logiciel si necessaire).

    installer.cmd          (double-clic, ou depuis PowerShell : .\installer.cmd)

  Le meme script pour tout le monde : TOUT le projet est installe (logiciels, Node.js, extensions VS Code, Git,
  cle SSH, dependances Python de tous les dossiers : API, Sentinel Brain, vision avec PyTorch CPU, modele YOLOv8n).
  N'importe quel poste peut ensuite devenir le serveur : verifier-serveur.cmd dit s'il en est capable.
  Option : -SkipSoftware saute l'etape 1 (logiciels deja installes).
  Le script peut etre relance sans risque : ce qui est deja installe est conserve.

  Etapes :
    1. Logiciels (winget)         Git, GitHub CLI, VS Code, Python 3.12, nvm, Docker Desktop
    2. Node.js                    version de .nvmrc, via nvm
    3. Extensions VS Code         celles de .vscode/extensions.json
    4. Git                        autocrlf=false, branche main, identite
    5. Cle SSH                    ed25519 pour GitHub
    6. Python                     .venv avec Python de .python-version et versions exactes (requirements-dev.txt)
    7. Controle                   tools\doctor.py
#>
param(
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
  # winget ecrit sur stderr : sous Windows PowerShell 5.1 avec 'Stop', cela arretait le script sans message.
  $ErrorActionPreference = 'Continue'
  try {
    $present = (& winget list --id $Id -e --accept-source-agreements --disable-interactivity 2>&1 | Out-String) -match [regex]::Escape($Id)
    if ($present) { Info "$Label : deja installe"; return }
    Info "$Label : installation..."
    & winget install --id $Id -e --silent --accept-package-agreements --accept-source-agreements --disable-interactivity 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Warn "$Label n'a pas pu etre installe automatiquement (code $LASTEXITCODE) : l'installer a la main." }
  } catch {
    Warn "$Label : winget a echoue ($($_.Exception.Message)). L'installer a la main, ou relancer avec -SkipSoftware."
  }
}

if (-not (Test-Path "$Root\.python-version") -or -not (Test-Path "$Root\requirements-dev.txt")) {
  throw "Lancer ce script depuis le depot Workshop-Sentinel-X clone (fichiers de versions introuvables)."
}
$PyVersion = (Get-Content "$Root\.python-version" -Raw).Trim()
$NodeVersion = (Get-Content "$Root\.nvmrc" -Raw).Trim()
Write-Host "Sentinel-X : installation de tout le projet (Python $PyVersion, Node $NodeVersion)" -ForegroundColor Green

# ------------------------------------------------------------------ 1. Logiciels
if (-not $SkipSoftware) {
  Step "1/7 Logiciels (winget, quelques minutes ; -SkipSoftware pour passer)"
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
  $wanted = $wanted | Where-Object { $_ -ne 'platformio.platformio-ide' }   # facultative (firmware dans l'Arduino IDE)
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
Info "PyTorch CPU et dependances de la vision (environ 1 Go, quelques minutes)"
& $py -m pip install -r ai\vision\torch-cpu.txt --index-url https://download.pytorch.org/whl/cpu --quiet
if ($LASTEXITCODE -ne 0) { throw "Installation de PyTorch CPU echouee (connexion Internet ?)." }
& $py -m pip install -r ai\vision\requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "Installation des dependances de la vision echouee." }
if (Test-Path ai\vision\models\yolov8n.pt) {
  Info "modele YOLOv8n deja present"
} else {
  Info "modele YOLOv8n (6 Mo) dans ai\vision\models : une fois, avec Internet ; la demo s'en passe ensuite"
  & $py -c "from ultralytics import YOLO; YOLO(r'ai\vision\models\yolov8n.pt')"
  if (-not (Test-Path ai\vision\models\yolov8n.pt)) { Warn "modele non telecharge : relancer installer.cmd avec Internet." }
}
Info "dependances installees"

# ------------------------------------------------------------------ 7. Controle
Step "7/7 Controle du poste"
& $py tools\doctor.py
$code = $LASTEXITCODE
Write-Host ""
if ($code -eq 0) {
  Write-Host "Poste conforme. Activer l'environnement a chaque session : .venv\Scripts\activate" -ForegroundColor Green
  Write-Host "Ce poste peut-il etre le serveur de la demo ? Lancer : verifier-serveur.cmd" -ForegroundColor Green
} else {
  Write-Host "Corriger les lignes [KO] ci-dessus (la commande est indiquee), puis relancer : python tools\doctor.py" -ForegroundColor Yellow
}
exit $code
