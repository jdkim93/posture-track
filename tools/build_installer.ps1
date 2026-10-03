param([string]$Iscc, [switch]$SkipDependencies)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    $taskPython = Join-Path (Get-Location) '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run setup.ps1 first.' }
    if (-not $SkipDependencies) {
        & $taskPython -m pip install -r requirements-build.txt
        if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
    }
    & $taskPython tools/prepare_models.py
    if ($LASTEXITCODE -ne 0) { throw 'Model preparation failed.' }
    & $taskPython -m PyInstaller --noconfirm PostureTrack.spec
    if ($LASTEXITCODE -ne 0) { throw 'Application packaging failed.' }
    if (-not $Iscc) {
        $taskCandidates = @('artifacts\InnoSetup\ISCC.exe', "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")
        $Iscc = $taskCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $Iscc) {
            $taskCompiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
            if ($taskCompiler) { $Iscc = $taskCompiler.Source }
        }
    }
    if (-not $Iscc) { throw 'Install Inno Setup 6 and pass -Iscc with the ISCC.exe path.' }
    & $Iscc installer/PostureTrack.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
    Write-Host 'Installer ready: dist\installer\PostureTrack-Setup-1.0.0.exe'
}
finally { Pop-Location }
