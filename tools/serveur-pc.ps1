<#
.SYNOPSIS
  Sentinel-X : prepare le PC serveur Windows 11 (pare-feu, heure NTP pour l'ESP, point d'acces Wi-Fi).

.DESCRIPTION
  A lancer UNE fois, dans un PowerShell ADMINISTRATEUR, depuis la racine du depot :

    powershell -ExecutionPolicy Bypass -File tools\serveur-pc.ps1                 # tout
    powershell -ExecutionPolicy Bypass -File tools\serveur-pc.ps1 -Action Verifier
    powershell -ExecutionPolicy Bypass -File tools\serveur-pc.ps1 -Action PointAcces -Ssid sentinel-x-g3

  Actions :
    PareFeu     autorise 443 (HTTPS) et 8883 (MQTTS) en entree, UNIQUEMENT depuis le reseau du point d'acces
                (192.168.137.0/24) ; -Dev ajoute 1883 (MQTT en clair, avant TLS) ; -Retirer supprime les regles
    Ntp         active le serveur de temps de Windows : l'ESP32-S3 se met a l'heure sur 192.168.137.1
                (indispensable au TLS et aux horodatages, meme sans Internet)
    PointAcces  demarre le point d'acces mobile Windows en 2,4 GHz (l'ESP32-S3 ne voit pas le 5 GHz)
    Verifier    controle le tout (sans rien modifier)
    Tout        PareFeu + Ntp + PointAcces + Verifier

  Le point d'acces mobile Windows donne toujours au PC l'adresse 192.168.137.1 : c'est l'adresse du broker
  dans firmware/include/secrets.h. Il exige que le PC soit relie a un reseau (Wi-Fi de l'ecole ou Ethernet) ;
  sinon, utiliser le routeur de secours (docs/reseau.md).
#>
param(
  [ValidateSet('Tout', 'PareFeu', 'Ntp', 'PointAcces', 'Verifier')]
  [string]$Action = 'Tout',
  [string]$Ssid = 'sentinel-x-gN',
  [switch]$Dev,
  [switch]$Retirer
)

$ErrorActionPreference = 'Stop'
$Subnet = '192.168.137.0/24'
$ServerIp = '192.168.137.1'
$RulePrefix = 'Sentinel-X'

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "   [OK] $msg" -ForegroundColor Green }
function Ko($msg) { Write-Host "   [KO] $msg" -ForegroundColor Red }
function Warn($msg) { Write-Host "   [!!] $msg" -ForegroundColor Yellow }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin -and $Action -ne 'Verifier') {
  throw "Lancer ce script dans un PowerShell ADMINISTRATEUR (clic droit > Executer en tant qu'administrateur)."
}

# ------------------------------------------------------------------ pare-feu
function Set-Firewall {
  Step "Pare-feu Windows : seuls 443 et 8883 depuis $Subnet"
  Get-NetFirewallRule -DisplayName "$RulePrefix*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
  if ($Retirer) { Ok "regles Sentinel-X supprimees"; return }
  $rules = @(
    @{ Name = "$RulePrefix HTTPS 443"; Port = 443; Proto = 'TCP' },
    @{ Name = "$RulePrefix MQTTS 8883"; Port = 8883; Proto = 'TCP' },
    @{ Name = "$RulePrefix NTP 123"; Port = 123; Proto = 'UDP' }
  )
  if ($Dev) { $rules += @{ Name = "$RulePrefix MQTT clair 1883 (temporaire)"; Port = 1883; Proto = 'TCP' } }
  foreach ($r in $rules) {
    New-NetFirewallRule -DisplayName $r.Name -Direction Inbound -Action Allow -Protocol $r.Proto `
      -LocalPort $r.Port -RemoteAddress $Subnet, 'LocalSubnet' -Profile Any | Out-Null
    Ok "$($r.Name) autorise depuis $Subnet"
  }
  if (-not $Dev) { Warn "1883 n'est pas ouvert. Avant le passage en TLS : relancer avec -Action PareFeu -Dev" }
}

# ------------------------------------------------------------------ serveur de temps
function Set-Ntp {
  Step "Serveur de temps (NTP) pour l'ESP32-S3"
  $base = 'HKLM:\SYSTEM\CurrentControlSet\Services\W32Time'
  Set-ItemProperty -Path "$base\TimeProviders\NtpServer" -Name Enabled -Value 1
  Set-ItemProperty -Path "$base\Config" -Name AnnounceFlags -Value 5
  Set-Service -Name W32Time -StartupType Automatic
  Restart-Service -Name W32Time
  w32tm /config /update | Out-Null
  Ok "serveur NTP actif : l'ESP utilise NTP_SERVER = $ServerIp"
}

# ------------------------------------------------------------------ point d'acces mobile
function Start-Hotspot {
  Step "Point d'acces Wi-Fi (2,4 GHz) '$Ssid'"
  if ($PSVersionTable.PSEdition -eq 'Core') {
    Warn "PowerShell 7 ne sait pas piloter le point d'acces : relance dans Windows PowerShell 5.1"
    $argList = "-ExecutionPolicy Bypass -File `"$PSCommandPath`" -Action PointAcces -Ssid $Ssid"
    Start-Process powershell.exe -ArgumentList $argList -Verb RunAs -Wait
    return
  }
  $pass = Read-Host "   Phrase de passe WPA2 (20 caracteres minimum, jamais dans le depot)" -AsSecureString
  $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pass))
  if ($plain.Length -lt 20) { throw "Phrase de passe trop courte (20 caracteres minimum)." }
  try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
    function Await($op, [Type]$type) {
      $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result
    }
    function AwaitAction($op) {
      $m = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } | Select-Object -First 1
      $m.Invoke($null, @($op)).Wait(-1) | Out-Null
    }
    $netProfile = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]::GetInternetConnectionProfile()
    if ($null -eq $netProfile) { throw "aucune connexion reseau source (Wi-Fi de l'ecole ou Ethernet requis)" }
    $tm = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]::CreateFromConnectionProfile($netProfile)
    $cfg = $tm.GetCurrentAccessPointConfiguration()
    $cfg.Ssid = $Ssid
    $cfg.Passphrase = $plain
    try { $cfg.Band = [Windows.Networking.NetworkOperators.TetheringWiFiBand]::TwoPointFourGigahertz } catch { Warn "bande non reglable sur cette carte : choisir 2,4 GHz dans Parametres" }
    AwaitAction ($tm.ConfigureAccessPointAsync($cfg))
    if ($tm.TetheringOperationalState -ne 'On') {
      $res = Await ($tm.StartTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
      if ($res.Status -ne 'Success') { throw "demarrage refuse : $($res.Status) $($res.AdditionalErrorMessage)" }
    }
    Ok "point d'acces '$Ssid' actif, PC = $ServerIp"
  } catch {
    Ko "pilotage automatique impossible : $_"
    Write-Host "   A la main : Parametres > Reseau et Internet > Point d'acces mobile :"
    Write-Host "   nom '$Ssid', mot de passe, bande 2,4 GHz, puis activer."
  }
}

# ------------------------------------------------------------------ verification
function Test-Server {
  Step "Verification du PC serveur"
  $ip = Get-NetIPAddress -IPAddress $ServerIp -ErrorAction SilentlyContinue
  if ($ip) { Ok "adresse $ServerIp presente (point d'acces actif)" } else { Ko "pas d'adresse $ServerIp : point d'acces arrete ?" }
  $rules = Get-NetFirewallRule -DisplayName "$RulePrefix*" -ErrorAction SilentlyContinue
  if ($rules) { Ok "regles de pare-feu : $(($rules | ForEach-Object DisplayName) -join ', ')" } else { Ko "aucune regle Sentinel-X : -Action PareFeu" }
  $ntp = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\W32Time\TimeProviders\NtpServer').Enabled
  if ($ntp -eq 1) { Ok "serveur NTP actif" } else { Warn "serveur NTP inactif : -Action Ntp" }
  foreach ($port in 8883, 443) {
    $l = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($l) { Ok "port $port en ecoute ($((Get-Process -Id $l[0].OwningProcess).ProcessName))" }
    else { Warn "port $port pas en ecoute : stack arretee ? (tools\demarrer.ps1)" }
  }
  docker info *> $null
  if ($LASTEXITCODE -eq 0) { Ok "Docker Desktop demarre" } else { Ko "Docker Desktop arrete" }
  $wifi = (Get-NetAdapter -Physical -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Up' } | ForEach-Object Name) -join ', '
  Write-Host "   interfaces actives : $wifi"
}

switch ($Action) {
  'PareFeu'    { Set-Firewall }
  'Ntp'        { Set-Ntp }
  'PointAcces' { Start-Hotspot }
  'Verifier'   { Test-Server }
  'Tout'       { Set-Firewall; Set-Ntp; Start-Hotspot; Test-Server }
}
