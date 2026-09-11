<#
.SYNOPSIS
    fivem-dev-kit client-side agent: uploads CitizenFX_log_*.log tail and
    profiler JSON dumps from this Windows gaming PC to the dev server's
    fivem-devtools resource, on an interval, forever.

.DESCRIPTION
    Runs entirely on the machine that plays the game (Windows). Requires
    nothing beyond PowerShell 5.1 (ships with Windows 10/11) -- no modules,
    no admin rights. This is the "upload" half of fivem-dev-kit's
    client-side observability; the fivem-devtools FiveM resource (running on
    the FXServer / Linux dev box) is the "receive" half. See
    $KIT/docs/fxclient.md for the full picture.

    Every loop tick (-IntervalMs, default 2000ms) this script:
      1. Tails the newest logs\CitizenFX_log_*.log under -FiveMDir and POSTs
         any new bytes to <server>/fivem-devtools/upload/clientlog. Handles
         log rotation and a game restart mid-run: a new newest file resets
         the read offset to the end of that new file (not 0 -- so an agent
         restart never re-uploads a whole historical log).
      2. Looks for citizen\devprofile-*.json (written by the client's
         `profiler saveJSON devprofile-<id>.json` console command -- see
         fivem-devtools' client/main.lua), uploads each to
         <server>/fivem-devtools/upload/profile?id=<id>, and renames it to
         *.uploaded on success so it is never re-sent. A failed upload is
         simply retried next tick, because the file is only renamed once the
         POST succeeds.
      3. Every ~30s (independent of -IntervalMs), prints one status line.

.PARAMETER Server
    The dev server's address as host:port, e.g. 192.168.1.10:30120 -- the
    same host:port you connect the game to. Required.

.PARAMETER FiveMDir
    FiveM's per-user data directory. Default: %LOCALAPPDATA%\FiveM\FiveM.app
    (the standard install location -- only change this if FiveM was pointed
    at a custom profile directory).

.PARAMETER IntervalMs
    Poll interval in milliseconds. Default 2000.

.EXAMPLE
    Run it directly, from the folder you saved it to:
        powershell -ExecutionPolicy Bypass -File fxclient-agent.ps1 -Server 192.168.1.10:30120

.EXAMPLE
    Fetch the latest copy straight from the dev server and run it, without
    saving it anywhere permanent first. `fxclient setup` (on the dev box)
    prints this one-liner with your actual LAN IP filled in:
        irm http://192.168.1.10:30120/fivem-devtools/agent -OutFile $env:TEMP\fxclient-agent.ps1
        powershell -ExecutionPolicy Bypass -File $env:TEMP\fxclient-agent.ps1 -Server 192.168.1.10:30120
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Server,

    [string]$FiveMDir = "$env:LOCALAPPDATA\FiveM\FiveM.app",

    [int]$IntervalMs = 2000
)

$ErrorActionPreference = 'Stop'
$BaseUrl = "http://$Server/fivem-devtools"
$LogsDir = Join-Path $FiveMDir 'logs'
$CitizenDir = Join-Path $FiveMDir 'citizen'

function Write-Status {
    param([string]$Message)
    $stamp = (Get-Date).ToString('HH:mm:ss')
    Write-Host "[$stamp] $Message"
}

Write-Status "fxclient-agent starting: server=$Server fiveMDir=$FiveMDir intervalMs=$IntervalMs"
Write-Status "watching $LogsDir\CitizenFX_log_*.log and $CitizenDir\devprofile-*.json"

if (-not (Test-Path $FiveMDir)) {
    Write-Status "WARN: -FiveMDir does not exist: $FiveMDir (check the path; nothing will upload until it does)"
}

# --- state -------------------------------------------------------------

$script:CurrentLogPath = $null
$script:LogOffset = 0
$script:LogBytesSent = 0
$script:ProfilesUploaded = 0
$script:LastError = $null
$script:LastOk = $true
$script:LastStatusAt = Get-Date

# --- helpers -------------------------------------------------------------

function Get-NewestLogFile {
    if (-not (Test-Path $LogsDir)) {
        return $null
    }
    # File names are CitizenFX_log_YYYY-MM-DDTHHMMSS.log -- fixed-width and
    # zero-padded, so a plain name sort is also a chronological sort (see
    # fivem/code/client/launcher/Console.Logging.cpp for the format).
    Get-ChildItem -Path $LogsDir -Filter 'CitizenFX_log_*.log' -File -ErrorAction SilentlyContinue |
        Sort-Object -Property Name -Descending |
        Select-Object -First 1
}

function Read-NewLogBytes {
    param([string]$Path, [long]$FromOffset)

    # Returns a single [PSCustomObject] (Bytes, Length) rather than a
    # positional array -- PowerShell's pipeline enumerates array output by
    # design (that's how e.g. Get-ChildItem streams multiple items), which
    # would silently unroll a `$buffer, $length` array into its individual
    # *bytes* followed by $length. A PSCustomObject isn't enumerated that
    # way, so it always arrives at the caller as exactly one object.
    #
    # FiveM keeps its own handle open on this file for append while the game
    # runs. Open our own with Read + ReadWrite sharing so we never fight it
    # for the lock.
    $stream = [System.IO.FileStream]::new($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $length = $stream.Length
        if ($length -le $FromOffset) {
            return [PSCustomObject]@{ Bytes = $null; Length = $length }
        }
        $stream.Seek($FromOffset, [System.IO.SeekOrigin]::Begin) | Out-Null
        $count = [int]($length - $FromOffset)
        $buffer = [byte[]]::new($count)
        $read = 0
        while ($read -lt $count) {
            $n = $stream.Read($buffer, $read, $count - $read)
            if ($n -le 0) { break }
            $read += $n
        }
        return [PSCustomObject]@{ Bytes = $buffer; Length = $length }
    }
    finally {
        $stream.Dispose()
    }
}

function Send-LogTail {
    $newest = Get-NewestLogFile
    if (-not $newest) {
        return
    }

    if ($script:CurrentLogPath -ne $newest.FullName) {
        # First run, a log rotation, or the game restarted -- (re)start from
        # the current end so an agent restart never replays a potentially
        # huge historical log.
        $script:CurrentLogPath = $newest.FullName
        $script:LogOffset = $newest.Length
        Write-Status "watching new log file: $($newest.Name) (starting at offset $($script:LogOffset))"
        return
    }

    $result = Read-NewLogBytes -Path $script:CurrentLogPath -FromOffset $script:LogOffset
    $bytes = $result.Bytes
    $newLength = $result.Length
    if (-not $bytes -or $bytes.Length -eq 0) {
        $script:LogOffset = $newLength
        return
    }

    # Round-trip through UTF-8 text: cheap sanitization in case a resource
    # printed non-UTF-8 bytes (invalid sequences become U+FFFD rather than
    # breaking the upload).
    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    $body = [System.Text.Encoding]::UTF8.GetBytes($text)
    try {
        Invoke-RestMethod -Method Post -Uri "$BaseUrl/upload/clientlog" -ContentType 'text/plain; charset=utf-8' -Body $body -TimeoutSec 10 | Out-Null
        $script:LogOffset = $newLength
        $script:LogBytesSent += $bytes.Length
        $script:LastOk = $true
    }
    catch {
        $script:LastError = $_.Exception.Message
        if ($script:LastOk) {
            Write-Status "WARN: clientlog upload failed, will retry: $($script:LastError)"
        }
        $script:LastOk = $false
        # leave LogOffset alone -- the same bytes are retried next tick
    }
}

function Send-Profiles {
    if (-not (Test-Path $CitizenDir)) {
        return
    }
    $files = Get-ChildItem -Path $CitizenDir -Filter 'devprofile-*.json' -File -ErrorAction SilentlyContinue
    foreach ($f in $files) {
        # Using the positive -match (not -notmatch) is deliberate: it's the
        # documented, unambiguous way to populate $Matches.
        if ($f.Name -match '^devprofile-(\d+)\.json$') {
            $id = $Matches[1]
            try {
                $fileBytes = [System.IO.File]::ReadAllBytes($f.FullName)
                Invoke-RestMethod -Method Post -Uri "$BaseUrl/upload/profile?id=$id" -ContentType 'application/json' -Body $fileBytes -TimeoutSec 30 | Out-Null
                Rename-Item -Path $f.FullName -NewName ($f.Name + '.uploaded') -Force
                $script:ProfilesUploaded++
                $script:LastOk = $true
                Write-Status "uploaded profile $($f.Name) (command id $id)"
            }
            catch {
                $script:LastError = $_.Exception.Message
                if ($script:LastOk) {
                    Write-Status "WARN: profile upload failed for $($f.Name), will retry: $($script:LastError)"
                }
                $script:LastOk = $false
                # file is left as-is (not renamed) -- retried next tick
            }
        }
    }
}

# --- main loop -----------------------------------------------------------

while ($true) {
    try {
        Send-LogTail
        Send-Profiles

        if (((Get-Date) - $script:LastStatusAt).TotalSeconds -ge 30) {
            if ($script:LastOk) {
                $reach = 'reachable'
            }
            else {
                $reach = "UNREACHABLE (last error: $($script:LastError))"
            }
            Write-Status "status: server=$Server $reach, logBytesSent=$($script:LogBytesSent), profilesUploaded=$($script:ProfilesUploaded), watching=$($script:CurrentLogPath)"
            $script:LastStatusAt = Get-Date
        }
    }
    catch {
        # Belt-and-suspenders: nothing in the loop body above should escape
        # its own try/catch, but this agent must never exit on its own
        # (short of Ctrl+C) -- an unhandled exception here would silently
        # stop all uploads for the rest of the play session.
        Write-Status "ERROR: unexpected failure in main loop, continuing: $($_.Exception.Message)"
    }

    Start-Sleep -Milliseconds $IntervalMs
}
