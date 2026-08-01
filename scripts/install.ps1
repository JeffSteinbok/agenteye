$ErrorActionPreference = "Stop"

$packageName = "agenteye-app"
$minimumVersion = [Version]"3.11"

function Test-PythonCandidate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [string[]]$Arguments = @()
    )

    $null = Get-Command $Command -ErrorAction SilentlyContinue
    if (-not $?) {
        return $false
    }

    & $Command @Arguments -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" *> $null
    return $LASTEXITCODE -eq 0
}

function Get-PythonCommand {
    $candidates = @(
        @{ Command = "py"; Arguments = @("-3.13") },
        @{ Command = "py"; Arguments = @("-3.12") },
        @{ Command = "py"; Arguments = @("-3.11") },
        @{ Command = "python"; Arguments = @() },
        @{ Command = "python3"; Arguments = @() }
    )

    foreach ($candidate in $candidates) {
        if (Test-PythonCandidate -Command $candidate.Command -Arguments $candidate.Arguments) {
            return $candidate
        }
    }

    throw "Agent Eye requires Python 3.11 or newer. Install Python first, then rerun this script."
}

$python = Get-PythonCommand
$pythonCommand = $python.Command
$pythonArguments = $python.Arguments

Write-Host "Installing Agent Eye for Windows using $pythonCommand $($pythonArguments -join ' ')..."

try {
    & $pythonCommand @pythonArguments -m ensurepip --upgrade *> $null
} catch {
}

& $pythonCommand @pythonArguments -m pip install --user --upgrade $packageName

$scriptsDir = (& $pythonCommand @pythonArguments -c 'import sysconfig; print(sysconfig.get_path("scripts", scheme=sysconfig.get_preferred_scheme("user")))' ).Trim()
$pythonExecutable = (& $pythonCommand @pythonArguments -c 'import os, sys; print(os.path.abspath(sys.executable))' ).Trim()

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$pathParts = @()
if ($userPath) {
    $pathParts = $userPath -split ";" | Where-Object { $_ }
}
if ($pathParts -notcontains $scriptsDir) {
    $newUserPath = (($pathParts + $scriptsDir) | Select-Object -Unique) -join ";"
    [Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
}

if ($env:Path -split ";" -notcontains $scriptsDir) {
    $env:Path = "$scriptsDir;$env:Path"
}

& $pythonCommand @pythonArguments -m src.session_dashboard _record-install `
    --method bootstrap-user-pip `
    --scripts-dir $scriptsDir `
    --path-target "User PATH" `
    --python-executable $pythonExecutable

$agentEyeExe = Join-Path $scriptsDir "agenteye.exe"
if (-not (Test-Path $agentEyeExe)) {
    throw "Agent Eye was installed, but $agentEyeExe was not found."
}

Write-Host "Agent Eye installed to $agentEyeExe"
Write-Host "User PATH updated. Open a new terminal if 'agenteye' is not yet available in your current shell."
