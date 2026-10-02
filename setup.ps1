$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $taskPython)) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Python 가상환경 생성에 실패했습니다.' }
    }
    & $taskPython -m pip install -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw '의존성 설치에 실패했습니다.' }
    & $taskPython tools/prepare_models.py
    if ($LASTEXITCODE -ne 0) { throw '모델 준비에 실패했습니다.' }
    Write-Host '설치 완료. .\start.ps1 로 실행하세요.'
}
finally { Pop-Location }
