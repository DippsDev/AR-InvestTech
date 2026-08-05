<#
.SYNOPSIS
    One-time VPS preparation: Python venv, dependencies, cloudflared, and a
    generated API token.

.DESCRIPTION
    Run once on a fresh Windows VPS, from the repo root, in an elevated
    PowerShell. Installing MetaTrader 5 and logging into it is a manual step
    (it is a GUI installer and needs your broker credentials) — see
    deploy/README.md.

    Safe to re-run: it skips work that is already done and never overwrites an
    existing .env.

.EXAMPLE
    .\deploy\setup_vps.ps1
#>
[CmdletBinding()]
param(
    # Where the tunnel will point. Only used to pre-fill the .env comment.
    [string] $PublicHostname = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Backend  = Join-Path $RepoRoot "backend"
$VenvDir  = Join-Path $RepoRoot ".venv"
$Python   = Join-Path $VenvDir "Scripts\python.exe"
$EnvFile  = Join-Path $Backend ".env"

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }

Step "Checking Python"
$sysPython = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $sysPython) {
    throw "Python not found on PATH. Install Python 3.11+ from python.org and tick 'Add python.exe to PATH'."
}
$ver = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$ver -lt [version]"3.11") {
    throw "Python $ver found, but 3.11+ is required (zoneinfo and the MT5 wheel depend on it)."
}
Ok "Python $ver at $sysPython"

Step "Creating virtual environment"
if (Test-Path $Python) {
    Ok "venv already exists at $VenvDir"
} else {
    & python -m venv $VenvDir
    Ok "Created $VenvDir"
}

Step "Installing dependencies"
& $Python -m pip install --upgrade pip --quiet
& $Python -m pip install -r (Join-Path $Backend "requirements.txt") --quiet
Ok "Installed backend/requirements.txt"

Step "Verifying the MetaTrader5 package"
# Windows-only wheel, and a numpy/MT5 ABI mismatch is a confusing way for
# everything downstream to fail — so it is worth checking here. But it must
# NOT abort the run: the .env written below is what the rest of the runbook
# depends on, and deploy/verify_vps.py re-checks MT5 properly later anyway.
#
# ErrorActionPreference is relaxed around the native call because in
# PowerShell 5.1 a native exe writing to stderr under -EA Stop raises
# NativeCommandError, which would terminate the script on a mere traceback.
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$mt5Out = & $Python -c "import MetaTrader5; print(MetaTrader5.__version__)" 2>&1
$mt5Ok  = ($LASTEXITCODE -eq 0)
$npOut  = & $Python -c "import numpy; print(numpy.__version__)" 2>&1
$npOk   = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevEAP

if ($npOk) {
    Ok "numpy $($npOut | Select-Object -Last 1)"
} else {
    Warn "numpy failed to import — see $npOut"
}

if ($mt5Ok) {
    Ok "MetaTrader5 $($mt5Out | Select-Object -Last 1) imports"
} else {
    Warn "MetaTrader5 failed to import. Continuing so .env is still written."
    Warn "Re-test it on its own after setup finishes:"
    Write-Host '        .\.venv\Scripts\python.exe -c "import MetaTrader5 as m; print(m.__version__)"' -ForegroundColor Gray
}

Step "Installing cloudflared"
$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cf) {
    foreach ($p in @("C:\Program Files (x86)\cloudflared\cloudflared.exe",
                     "C:\Program Files\cloudflared\cloudflared.exe")) {
        if (Test-Path $p) { $cf = $p; break }
    }
}
if ($cf) {
    Ok "cloudflared already present at $cf"
} elseif (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "  Installing via winget..."
    winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
    Ok "cloudflared installed (open a new shell for it to appear on PATH)"
} else {
    # Windows Server SKUs ship without App Installer, so winget is absent.
    # This must not abort the run: cloudflared is frequently already installed
    # (or managed from the Zero Trust dashboard), and the steps after this one
    # — writing .env with a generated API_TOKEN — are the ones that matter.
    Warn "winget not available and cloudflared not found on PATH."
    Warn "If the tunnel is not already running, install it manually from:"
    Write-Host "        https://github.com/cloudflare/cloudflared/releases/latest (cloudflared-windows-amd64.msi)" -ForegroundColor Gray
}

Step "Configuring .env"
if (Test-Path $EnvFile) {
    Ok ".env already exists — leaving it untouched"
    $envText = Get-Content $EnvFile -Raw
    if ($envText -notmatch '(?m)^API_TOKEN=\S') {
        Warn "API_TOKEN is empty. Generate one with:"
        Write-Host '        python -c "import secrets; print(secrets.token_urlsafe(32))"' -ForegroundColor Gray
    }
} else {
    # 32 bytes of CSPRNG entropy, url-safe. Not Get-Random, which is not
    # cryptographically secure and would be guessable.
    $token = & $Python -c "import secrets; print(secrets.token_urlsafe(32))"
    # Built before the here-string: PowerShell 5.1 cannot parse a double-quoted
    # string inside a $() subexpression within a double-quoted here-string.
    $hostLine = ""
    if ($PublicHostname) { $hostLine = "# Public URL: $PublicHostname" }
    @"
# --- MT5 (fill these in) ---
MT5_LOGIN=
MT5_PASSWORD=
MT5_SERVER=
MT5_PATH=

# --- API ---
# Required: the tunnel makes these routes internet-reachable.
API_TOKEN=$token
AR_BIND_HOST=127.0.0.1
AR_BIND_PORT=8000
$hostLine

# --- Risk ---
SB_RISK_PCT=1.0
SB_NEWS=true
SB_MAX_DRAWDOWN_PCT=50.0
SB_DAILY_LOSS_LIMIT_USD=10.0
SB_MAX_TRADES_PER_DAY=5
TL_ENABLED=true
TL_NEWS=true
MB_ENABLED=false
"@ | Set-Content -Path $EnvFile -Encoding utf8
    Ok "Wrote $EnvFile with a generated API_TOKEN"
    Warn "Fill in MT5_LOGIN / MT5_PASSWORD / MT5_SERVER before continuing."
}

Step "Next steps"
Write-Host @"
  1. Install MetaTrader 5 and log in to your broker account (manual).
     Then: Tools > Options > Expert Advisors > enable algorithmic trading,
     and press the AutoTrading toolbar button so it is green.
  2. Fill in MT5_LOGIN / MT5_PASSWORD / MT5_SERVER in:
        $EnvFile
  3. Set up the named Cloudflare tunnel  (deploy/README.md, step 5)
  4. Enable auto-logon + autostart        .\deploy\install_autostart.ps1
  5. Verify                               $Python deploy\verify_vps.py
"@ -ForegroundColor Gray
