<#
    n8n başlatıcı.

    n8n `>=20.19 <25` istiyor; bu makinedeki sistem Node'u 25.9.0 (Remotion için uygun).
    nvm-windows kurmak yerine taşınabilir Node 22 kullanıyoruz: sistem PATH'i
    değişmiyor, admin gerekmiyor, mevcut Node 25 kurulumu bozulmuyor.

    KOD C:'DE, VERİ D:'DE. İlk denemede npm-global harici diske kurulmuştu ve
    45 dakikada sadece 31 MB yazabildi — n8n'in bağımlılık ağacı on binlerce küçük
    dosya ve exFAT/USB bunu kaldırmıyor. Node ve n8n artık C:'de (~1.5 GB);
    D:'de yalnızca n8n verisi (workflow'lar, kimlik bilgileri, SQLite) yaşıyor.

    Kullanım:
        .\scripts\n8n.ps1            # n8n'i başlat
        .\scripts\n8n.ps1 -Install   # n8n'i kur veya güncelle
        .\scripts\n8n.ps1 -Version   # sürümleri göster
#>

[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Version
)

$ErrorActionPreference = 'Stop'

# Kod C:'de — çok sayıda küçük dosya, exFAT'te değil.
$ToolsRoot = Join-Path $env:LOCALAPPDATA "otomasyon-tools"
$NodeHome = Join-Path $ToolsRoot "node22"
$NodeExe = Join-Path $NodeHome "node.exe"
$NpmCmd = Join-Path $NodeHome "npm.cmd"

if (-not (Test-Path $NodeExe)) {
    Write-Error "Taşınabilir Node 22 bulunamadı: $NodeHome`nKurulum için docs/setup.md Adım 1'e bak."
}

$env:NPM_CONFIG_PREFIX = Join-Path $ToolsRoot "npm-global"
$env:NPM_CONFIG_CACHE = Join-Path $ToolsRoot "npm-cache"

# Bu oturum için Node 22 öne alınır. Kalıcı PATH değişikliği YOK.
$env:PATH = "$NodeHome;$($env:NPM_CONFIG_PREFIX);$env:PATH"

# n8n verisi (workflow'lar, kimlik bilgileri, SQLite) C:'de kalir.
# "Veri D:'de" kurali AGIR medya icindir: render ciktisi, modeller, asset'ler.
# n8n'in durumu birkac on MB ve operasyonel olarak kritik — harici disk cikarildiginda
# n8n'in hic acilmamasi kabul edilemez.
$env:N8N_USER_FOLDER = Join-Path $ToolsRoot "n8n"
New-Item -ItemType Directory -Path $env:N8N_USER_FOLDER -Force | Out-Null

if ($Version) {
    Write-Output ("node : " + (& $NodeExe --version))
    Write-Output ("npm  : " + (& $NpmCmd --version))
    $n8nExe = Join-Path $env:NPM_CONFIG_PREFIX "n8n.cmd"
    if (Test-Path $n8nExe) { Write-Output ("n8n  : " + (& $n8nExe --version)) }
    else { Write-Output "n8n  : kurulu degil (-Install ile kur)" }
    Write-Output ("veri : " + $env:N8N_USER_FOLDER)
    return
}

if ($Install) {
    Write-Output "n8n kuruluyor ($env:NPM_CONFIG_PREFIX)..."
    Write-Output "Bagimlilik agaci buyuk (~230k dosya, ~1.6 GB); birkac dakika surer."

    # npm uyarilari (ERESOLVE peer dependency vb.) stderr'e yazar. PowerShell 5.1
    # bunlari ErrorRecord'a sarar ve $ErrorActionPreference='Stop' altinda kurulum
    # basarili olsa bile betigi oldurur. Gercek basari olcutu $LASTEXITCODE.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $NpmCmd install -g n8n
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }

    if ($code -ne 0) {
        Write-Error "npm install basarisiz (cikis kodu $code)."
    }

    $installed = Join-Path $env:NPM_CONFIG_PREFIX "n8n.cmd"
    if (-not (Test-Path $installed)) {
        Write-Error "npm 0 dondu ama n8n.cmd olusmadi: $installed"
    }

    Write-Output "Tamam: $installed"
    return
}

$n8nExe = Join-Path $env:NPM_CONFIG_PREFIX "n8n.cmd"
if (-not (Test-Path $n8nExe)) {
    Write-Error "n8n kurulu degil. Once sunu calistir:`n  .\scripts\n8n.ps1 -Install"
}

# .env'den port/host oku
$envFile = Join-Path $PSScriptRoot "..\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*N8N_PORT\s*=\s*(.+)\s*$') { $env:N8N_PORT = $Matches[1].Trim() }
        if ($_ -match '^\s*N8N_HOST\s*=\s*(.+)\s*$') { $env:N8N_HOST = $Matches[1].Trim() }
    }
}
if (-not $env:N8N_PORT) { $env:N8N_PORT = "5678" }
if (-not $env:N8N_HOST) { $env:N8N_HOST = "127.0.0.1" }

Write-Output "n8n baslatiliyor -> http://$($env:N8N_HOST):$($env:N8N_PORT)"
Write-Output "Durdurmak icin Ctrl+C"
Write-Output ""
& $n8nExe start
