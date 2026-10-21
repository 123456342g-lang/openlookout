# One-command setup for the resident sprite. Run from the repository root.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Invoke-Py {
    param([string[]]$PyArgs)
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.11 @PyArgs
    } else {
        & python @PyArgs
    }
    return $LASTEXITCODE
}

$version = Invoke-Py @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")
if ($version -ne 0) {
    Write-Error "Python 3.11 or newer is required."
    exit 1
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
