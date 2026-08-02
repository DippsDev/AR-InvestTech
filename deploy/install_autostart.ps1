<#
.SYNOPSIS
    Make MT5 and the backend start automatically after a VPS reboot.

.DESCRIPTION
    MetaTrader 5 is a GUI application: the Python SDK talks to terminal64.exe
    over a named pipe, and the terminal only runs inside an interactive
    desktop session. That single fact drives this whole design —

      * A Windows *service* (NSSM, LocalSystem) cannot host MT5, and a service
        in session 0 generally cannot reach a terminal running in session 1.
      * So the VPS must auto-logon to a desktop session at boot regardless.
      * Once it does, scheduled tasks triggered "at logon" run in that same
        session as that same user, so the named pipe just works.

    This registers two logon-triggered scheduled tasks (MT5, then the backend
    API) and optionally configures auto-logon.

    IMPORTANT once running: disconnect from RDP (close the window), never
    "Sign out". Signing out destroys the session and kills MT5.

.PARAMETER EnableAutoLogon
    Also configure Windows auto-logon. This writes the account password to
    HKLM in PLAINTEXT, readable by any local administrator. On a
    single-purpose trading VPS that is the normal trade-off, but make it
    knowingly: use a dedicated account, and never reuse the password.

.EXAMPLE
    .\deploy\install_autostart.ps1
    .\deploy\install_autostart.ps1 -EnableAutoLogon
#>
[CmdletBinding()]
param(
    [switch] $EnableAutoLogon,
    [string] $Mt5Path = "",
    [string] $TaskPrefix = "AR-InvestTech"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Backend  = Join-Path $RepoRoot "backend"
$Python   = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Server   = Join-Path $Backend "server.py"

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }

if (-not (Test-Path $Python)) { throw "venv not found at $Python. Run .\deploy\setup_vps.ps1 first." }
if (-not (Test-Path $Server)) { throw "server.py not found at $Server." }

Step "Locating MetaTrader 5"
if (-not $Mt5Path) {
    $running = Get-Process terminal64 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($running) {
        $Mt5Path = $running.Path
    } else {
        foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
            if (-not $root) { continue }
            $hit = Get-ChildItem -Path $root -Filter terminal64.exe -Recurse -Depth 2 -ErrorAction SilentlyContinue |
                   Select-Object -First 1
            if ($hit) { $Mt5Path = $hit.FullName; break }
        }
    }
}
if ($Mt5Path -and (Test-Path $Mt5Path)) {
    Ok "MT5: $Mt5Path"
} else {
    Warn "terminal64.exe not found. Install MT5 first, or pass -Mt5Path."
    Warn "Skipping the MT5 autostart task; the backend task will still be registered."
    $Mt5Path = ""
}

$user = "$env:USERDOMAIN\$env:USERNAME"
Step "Registering scheduled tasks as $user"

# MT5 first, with a delay so the network stack and broker DNS are up before
# the terminal tries to reach the trade server.
if ($Mt5Path) {
    $name = "$TaskPrefix-MT5"
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    $action  = New-ScheduledTaskAction -Execute $Mt5Path
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $trigger.Delay = "PT30S"
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
        -Settings $settings -RunLevel Highest -Description "Starts MetaTrader 5 for the trading bot." | Out-Null
    Ok "$name registered (30s after logon)"
}

# Backend second, with a longer delay: bridge.resume_on_startup() connects to
# MT5 immediately, and that fails if the terminal has not finished logging in.
$name = "$TaskPrefix-API"
Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
$action  = New-ScheduledTaskAction -Execute $Python -Argument "`"$Server`"" -WorkingDirectory $Backend
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = "PT2M"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Settings $settings -RunLevel Highest -Description "AR-InvestTech backend API." | Out-Null
Ok "$name registered (2min after logon, restarts up to 5x on failure)"

if ($EnableAutoLogon) {
    Step "Configuring auto-logon"
    Write-Host "  The password is stored in plaintext in the registry." -ForegroundColor Yellow
    $sec = Read-Host -AsSecureString "  Password for $user"
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    $key = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
    Set-ItemProperty $key "AutoAdminLogon" "1"
    Set-ItemProperty $key "DefaultUserName" $env:USERNAME
    Set-ItemProperty $key "DefaultDomainName" $env:USERDOMAIN
    Set-ItemProperty $key "DefaultPassword" $plain
    Ok "Auto-logon enabled for $user"
} else {
    Step "Auto-logon NOT configured"
    Write-Host @"
  Without auto-logon, a reboot leaves the VPS at the lock screen with no
  desktop session — MT5 will not start and the bot will not trade until you
  RDP in. Re-run with -EnableAutoLogon once you have read the warning above.
"@ -ForegroundColor Yellow
}

Step "Done"
Write-Host @"
  Verify now:      $Python deploy\verify_vps.py
  Test a reboot:   Restart-Computer   (then wait ~3 min and re-run verify)
  Task status:     Get-ScheduledTask -TaskName "$TaskPrefix-*"

  REMEMBER: close RDP with 'disconnect', never 'Sign out' — signing out
  ends the session and stops MT5.
"@ -ForegroundColor Gray
