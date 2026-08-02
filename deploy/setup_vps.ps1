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
# This wheel is Windows-only; a silent failure here is the single most
# confusing way for the whole deployment to not work.
& $Python -c "import MetaTrader5; print('  MetaTrader5', MetaTrader5.__version__)"
Ok "MetaTrader5 package imports"

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
} else {
    Write-Host "  Installing via winget..."
    winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
    Ok "cloudflared installed (open a new shell for it to appear on PATH)"
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
