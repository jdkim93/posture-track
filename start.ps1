param([switch]$Demo, [switch]$DevAlerts, [switch]$ReleaseAlerts, [switch]$ValidationCapture)
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw '프로젝트 가상환경이 없습니다. README.md의 설치 절차를 확인하세요.'
}
$taskArguments = @('-m', 'posture_track')
if ($Demo) { $taskArguments += '--demo' }
if ($DevAlerts) { $taskArguments += '--dev-alerts' }
if ($ReleaseAlerts) { $taskArguments += '--release-alerts' }
if ($ValidationCapture) { $taskArguments += @('--validation-capture', '--data-dir', '.data/validation-live') }
Push-Location $PSScriptRoot
try { & $taskPython @taskArguments }
finally { Pop-Location }
