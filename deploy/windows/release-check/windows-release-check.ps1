# The Windows release check (task 186, step 186-06): what a real Windows 11 computer proves before
# rouh.land offers Rouh to Windows, and again for each release. GitHub's Windows machines cannot
# run WSL2, so this runs on Rouh's own Windows test computer, by hand or as the self-hosted runner
# of .github/workflows/windows-release-check.yml. Every step's words go to -Out, and result.json
# says which passed; a step that cannot run here says so as skipped, never as passed.
#
#     powershell -ExecutionPolicy Bypass -File windows-release-check.ps1 [-Installer PATH|URL]
#         [-Out DIR] [-IdleMinutes 15] [-Sleep] [-KeepAfter]
#
#   1. from empty: no Rouh, then install.ps1 as a person runs it (ROUH_YES), and everything it set
#      up checked from Windows: the Linux and its lock-down, .wslconfig, the task at sign-in, the
#      page on http://127.0.0.1:8420, the setup address, the worker's Landlock walls inside WSL's kernel;
#   2. left alone: nothing touches it for -IdleMinutes, and it is still up (WSL's idle shut-down);
#   3. update, and back;
#   4. sleep and wake (-Sleep): the computer suspends for two minutes, wakes by a timer, and Rouh
#      answers again within two minutes;
#   5. uninstall, Keep my data, then install again: the same Rouh comes back (its fingerprint);
#   6. uninstall, Wipe my data (unless -KeepAfter): nothing of Rouh's is left.
# The restart of Windows and a real phone over the relay are a person's checks (INSTALL-WINDOWS.md).
param(
    [string]$Installer = 'https://rouh.land/install.ps1',
    [string]$Out = (Join-Path $env:TEMP ("rouh-release-check-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))),
    [int]$IdleMinutes = 15,
    [switch]$Sleep,
    [switch]$KeepAfter
)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$log = Join-Path $Out 'check.log'
$results = [ordered]@{}
function Note([string]$t) { $line = "$(Get-Date -Format 'HH:mm:ss') $t"; Write-Host $line; Add-Content -Path $log -Value $line }
function Pass([string]$id) { $results[$id] = 'pass'; Note "PASS $id" }
function Fail([string]$id, [string]$why) { $results[$id] = 'fail'; Note "FAIL $id - $why" }
function Skip([string]$id, [string]$why) { $results[$id] = 'skipped'; Note "SKIP $id - $why" }
function Check([string]$id, [scriptblock]$test, [string]$why) {
    try { if (& $test) { Pass $id } else { Fail $id $why } } catch { Fail $id "$why ($($_.Exception.Message))" }
}

$env:WSL_UTF8 = '1'
$rouhPs1 = Join-Path $env:LOCALAPPDATA 'Rouh\rouh.ps1'
function Wsl([string[]]$a) { $o = & wsl.exe @a 2>&1 | ForEach-Object { "$_" }; Add-Content -Path $log -Value ($o -join "`n"); return @{ Code = $LASTEXITCODE; Out = $o } }
function InRouh([string]$cmd) { return Wsl @('-d', 'Rouh', '-u', 'rouh', '--cd', '~', '--', 'sh', '-lc', $cmd) }
function State { $r = Wsl @('-d', 'Rouh', '-u', 'rouh', '--cd', '~', '--', '/usr/local/bin/rouh-wsl', 'state'); return ($r.Out | Where-Object { $_ -match '^\{' } | Select-Object -Last 1 | ConvertFrom-Json) }
function Answers { try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 'http://127.0.0.1:8420/healthz').StatusCode -eq 200 } catch { $false } }
function WaitAnswers([int]$seconds) { $end = (Get-Date).AddSeconds($seconds); while ((Get-Date) -lt $end) { if (Answers) { return $true }; Start-Sleep 5 }; return $false }
function Distros { (Wsl @('--list', '--quiet')).Out | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ } }
function RunInstaller([string[]]$words) {
    $env:ROUH_YES = '1'; $env:ROUH_NO_OPEN = '1'
    $file = $Installer
    if ($Installer -match '^https://') { $file = Join-Path $Out 'install.ps1'; Invoke-WebRequest -UseBasicParsing $Installer -OutFile $file }
    $o = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $file @words 2>&1 | ForEach-Object { "$_" }
    Add-Content -Path $log -Value ($o -join "`n")
    return $LASTEXITCODE
}

$facts = Get-CimInstance Win32_OperatingSystem
Note "Windows $($facts.Caption) build $($facts.BuildNumber), $env:PROCESSOR_ARCHITECTURE; $((Wsl @('--version')).Out -join ' | ')"

# --- 1. from empty -------------------------------------------------------------------------------
if ((Distros) -contains 'Rouh') { Note 'Rouh is installed already: wiping it first, for a check from empty'; $null = RunInstaller @('uninstall', '-Wipe', '-Yes') }
Check 'empty.before' { -not ((Distros) -contains 'Rouh') } 'Rouh is still installed'
$t0 = Get-Date
$code = RunInstaller @()
Note ("install.ps1 took {0:N0} minutes" -f ((Get-Date) - $t0).TotalMinutes)
Check 'install.exit' { $code -eq 0 } "install.ps1 exited $code"
Check 'install.distro' { (Distros) -contains 'Rouh' } 'no Rouh in wsl --list'
Check 'install.wsl2' { ((Wsl @('--list', '--verbose')).Out -join "`n") -match 'Rouh\s+\S+\s+2' } 'Rouh is not a WSL 2 Linux'
Check 'lockdown.no-windows-drives' { (InRouh 'test ! -e /mnt/c/Windows').Code -eq 0 } '/mnt/c is mounted inside'
Check 'lockdown.no-interop' { (InRouh 'cmd.exe /c ver').Code -ne 0 } 'a Windows program ran from inside'
Check 'lockdown.no-general-sudo' { (InRouh 'sudo -n true').Code -ne 0 } 'rouh has general sudo'
Check 'linux.systemd' { (InRouh 'systemctl is-system-running').Out -match 'running|degraded' } 'systemd is not running'
Check 'linux.docker' { (InRouh 'docker info --format {{.ServerVersion}}').Code -eq 0 } 'Docker does not answer inside'
$cfg = Get-Content -Raw (Join-Path $env:USERPROFILE '.wslconfig') -ErrorAction SilentlyContinue
Check 'wslconfig' { $cfg -match 'vmIdleTimeout=-1' -and $cfg -match 'memory=' } '.wslconfig lacks the idle timeout or the memory cap'
Check 'keep-running.task' { $null -ne (Get-ScheduledTask -TaskName 'Rouh keeps running' -ErrorAction SilentlyContinue) } 'no task at sign-in'
Check 'page.from-windows' { WaitAnswers 120 } 'http://127.0.0.1:8420/healthz does not answer from Windows'
$s = State
Check 'state.running-no-owner' { $s.running -and ($s.owner -eq $false) } "state: $($s | ConvertTo-Json -Compress)"
$link = (Wsl @('-d', 'Rouh', '-u', 'rouh', '--cd', '~', '--', '/usr/local/bin/rouh-wsl', 'link')).Out | Select-Object -Last 1
Check 'setup.link-opens' { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 $link).StatusCode -eq 200 } "the setup address $($link -replace 'code=.*','code=...') did not open"
Check 'walls.landlock' { (InRouh 'cat /sys/kernel/security/lsm').Out -match 'landlock' } 'WSL''s kernel has no Landlock switched on'
Check 'walls.worker' { (InRouh 'docker compose -p rouh -f ~/rouh/stack/stack.json exec -T worker id -u').Out -match '^[1-9]' } 'the worker does not run, or runs as root'
Check 'timer.nightly' { (InRouh 'systemctl is-enabled rouh-update.timer').Out -match 'enabled' } 'the nightly update timer is off'

# --- 2. left alone -------------------------------------------------------------------------------
if ($IdleMinutes -gt 0) {
    Note "Leaving it alone for $IdleMinutes minutes"
    Start-Sleep -Seconds ($IdleMinutes * 60)
    Check 'idle.still-up' { Answers } "Rouh stopped answering after $IdleMinutes idle minutes"
} else { Skip 'idle.still-up' '-IdleMinutes 0' }

# --- 3. update and back --------------------------------------------------------------------------
$code = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $rouhPs1 update 2>&1 | Out-File -Append $log; $code = $LASTEXITCODE
Check 'update' { $code -eq 0 -and (WaitAnswers 300) } "rouh.ps1 update exited $code"
$prev = (InRouh 'test -f ~/rouh/releases/previous.json').Code -eq 0
if ($prev) {
    $code = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $rouhPs1 back 2>&1 | Out-File -Append $log; $code = $LASTEXITCODE
    Check 'back' { $code -eq 0 -and (WaitAnswers 300) } "rouh.ps1 back exited $code"
} else { Skip 'back' 'no release before this one on this computer yet (a fresh install has one release)' }

# --- 4. sleep and wake ---------------------------------------------------------------------------
if ($Sleep) {
    $wake = (Get-Date).AddMinutes(2)
    $a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c exit'
    $tr = New-ScheduledTaskTrigger -Once -At $wake
    $st = New-ScheduledTaskSettingsSet -WakeToRun
    Register-ScheduledTask -TaskName 'Rouh release check wake' -Action $a -Trigger $tr -Settings $st -Force | Out-Null
    Note "Suspending; the wake timer is at $($wake.ToString('HH:mm:ss'))"
    Add-Type -AssemblyName System.Windows.Forms
    $null = [System.Windows.Forms.Application]::SetSuspendState([System.Windows.Forms.PowerState]::Suspend, $false, $false)
    Start-Sleep -Seconds 20
    Unregister-ScheduledTask -TaskName 'Rouh release check wake' -Confirm:$false
    Check 'sleep.wake' { WaitAnswers 120 } 'Rouh did not answer within two minutes of waking'
} else { Skip 'sleep.wake' 'run with -Sleep on a computer that can be suspended' }

# --- 5. Keep my data, then Bring back ------------------------------------------------------------
$before = ((InRouh 'rouh fingerprint').Out -join "`n")
$code = RunInstaller @('uninstall', '-Keep', '-Yes')
$kept = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Rouh\Kept') -Filter 'Rouh-kept-*.tar' -ErrorAction SilentlyContinue
Check 'keep.saved' { $code -eq 0 -and $kept -and -not ((Distros) -contains 'Rouh') } "uninstall -Keep exited $code"
$code = RunInstaller @()
Check 'keep.bring-back' { $code -eq 0 -and (WaitAnswers 600) } "install after Keep exited $code"
$after = ((InRouh 'rouh fingerprint').Out -join "`n")
Check 'keep.same-rouh' { $before -and ($before -eq $after) } 'the Rouh that came back is not the one that was kept'

# --- 6. Wipe my data -----------------------------------------------------------------------------
if (-not $KeepAfter) {
    $code = RunInstaller @('uninstall', '-Wipe', '-Yes')
    Check 'wipe' { $code -eq 0 -and -not ((Distros) -contains 'Rouh') -and -not (Get-ScheduledTask -TaskName 'Rouh keeps running' -ErrorAction SilentlyContinue) } 'Rouh is still there after Wipe'
} else { Skip 'wipe' '-KeepAfter' }

$failed = @($results.Keys | Where-Object { $results[$_] -eq 'fail' })
$doc = [ordered]@{ ok = ($failed.Count -eq 0); at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); windows = "$($facts.Caption) $($facts.BuildNumber)"; arch = $env:PROCESSOR_ARCHITECTURE; results = $results }
$doc | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $Out 'result.json')
Note ("{0} passed, {1} failed, {2} skipped. Results: {3}" -f @($results.Values | Where-Object { $_ -eq 'pass' }).Count, $failed.Count, @($results.Values | Where-Object { $_ -eq 'skipped' }).Count, $Out)
if ($failed.Count -gt 0) { exit 1 }
