$ErrorActionPreference = 'Stop'

Set-Location -Path $PSScriptRoot

$VenvDir = Join-Path $PSScriptRoot 'venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$ActivateScript = Join-Path $VenvDir 'Scripts\Activate.ps1'

$Created = $false
if (-not (Test-Path -Path $VenvPython)) {
  Write-Host "[run.ps1] venv not found, creating '$VenvDir'..."
  if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 -m venv $VenvDir
  } else {
    & python -m venv $VenvDir
  }
  $Created = $true
}

if (-not (Test-Path -Path $VenvPython)) {
  throw "[run.ps1] venv python not found at '$VenvPython'. Please install Python 3."
}

if ($Created) {
  & $VenvPython -m pip install --upgrade pip
  if (Test-Path -Path (Join-Path $PSScriptRoot 'requirements.txt')) {
    & $VenvPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
  }
}

if (-not (Test-Path -Path $ActivateScript)) {
  throw "[run.ps1] Activate script not found at '$ActivateScript'."
}

& $ActivateScript
python .\run.py
exit $LASTEXITCODE

