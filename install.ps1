# One-command setup for the resident sprite. Run from the repository root.
# Pick one Python >= 3.11 (py -3, then python) and use only that interpreter.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Test-PythonAtLeast311 {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Prefix)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & @Prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $previous
    }
}

$Py = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    if (Test-PythonAtLeast311 py -3) {
        $Py = @("py", "-3")
    }
}
if (-not $Py -and (Get-Command python -ErrorAction SilentlyContinue)) {
    if (Test-PythonAtLeast311 python) {
        $Py = @("python")
    }
}
if (-not $Py) {
    Write-Error "Python 3.11 or newer is required."
    exit 1
}

function Invoke-Py {
    param([string[]]$PyArgs)
    & @($script:Py + $PyArgs)
    return $LASTEXITCODE
}

Set-Location (Join-Path $PSScriptRoot "src\openlookout")
$install = Invoke-Py @("-m", "pip", "install", "pillow", "psutil", "jsonschema", "certifi", "-r", "requirements-proactive.txt")
if ($install -ne 0) { exit $install }

$tray = Invoke-Py @("-m", "pip", "install", "pystray")
if ($tray -ne 0) {
    Write-Host "pystray is optional. Right-click Pause, Undo, and Quit still work."
}

$wizard = Invoke-Py @("-m", "sprite.proactive.first_run")
if ($wizard -ne 0) { exit $wizard }

Invoke-Py @("-m", "sprite.proactive.live")
exit $LASTEXITCODE
