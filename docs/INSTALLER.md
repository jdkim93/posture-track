# Windows 인스톨러 빌드

Windows x64, Python 3.13 및 Inno Setup 6.7 이상을 사용합니다.

```powershell
.\setup.ps1
.\tools\build_installer.ps1 -Iscc 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
```

빌드 스크립트는 빌드 의존성을 설치하고 모델을 준비한 뒤, PyInstaller의 폴더형 배포물을 Inno Setup으로 묶습니다. 결과는 `dist/installer/PostureTrack-Setup-1.0.0.exe`입니다. 모델·Python·Tk·MediaPipe를 포함하며, 개인 데이터와 가상환경 전체는 포함하지 않습니다. 설치 파일 자체는 코드 서명하지 않았습니다.

설치 옵션의 `autostart`는 최초 설치에서 선택됩니다. 재설치는 이전 선택을 유지합니다. 자동 실행 등록은 현재 사용자의 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`에 `PostureTrack`이라는 값으로 저장되며 `--background`로 실행합니다. 옵션을 끄고 재설치하거나 앱을 제거하면 해당 값만 삭제합니다. Windows 작업 관리자의 시작 앱에서 사용자가 별도로 비활성화한 상태는 Windows가 관리합니다.

설치 파일의 버전은 `installer/PostureTrack.iss`의 `AppVersion`으로 관리합니다. AppId는 업그레이드와 제거에 사용하므로 유지하세요.

## 패키지 검증

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
$taskCheck = Start-Process .\dist\PostureTrack\PostureTrack.exe -ArgumentList '--self-check', "$PWD\artifacts\package-check.json" -Wait -PassThru
$taskCheck.ExitCode
Get-Content artifacts/package-check.json
$taskUi = Start-Process .\dist\PostureTrack\PostureTrack.exe -ArgumentList '--demo', '--ui-smoke', '--data-dir', "$PWD\artifacts\package-ui" -Wait -PassThru
$taskUi.ExitCode
```

`--self-check`는 카메라를 열지 않고 포함한 이미지·모델을 확인하고 빈 이미지 추론을 실행합니다. `--ui-smoke`는 데모 화면의 위젯 동작을 확인합니다. 실제 웹캠 감지 품질은 별도로 확인해야 합니다.

GitHub Actions의 Windows installer 워크플로를 수동 실행하거나 v로 시작하는 태그를 푸시하면 설치 파일을 빌드하여 다운로드 가능한 아티팩트로 보관합니다.
