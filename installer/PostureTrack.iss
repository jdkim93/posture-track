#define AppVersion "1.0.0"
[Setup]
AppId={{907AC51C-A967-4190-978B-604C7B3A3EA1}
AppName=Posture Track
AppVersion={#AppVersion}
AppPublisher=jdkim93
DefaultDirName={localappdata}\Programs\PostureTrack
DefaultGroupName=Posture Track
PrivilegesRequired=lowest
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=PostureTrack-Setup-{#AppVersion}
SetupIconFile=..\assets\posture-track.ico
UninstallDisplayIcon={app}\PostureTrack.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UsePreviousTasks=yes
CloseApplications=yes
RestartApplications=no
[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
[CustomMessages]
korean.AutoStart=Windows 로그인 시 자동 실행 (트레이에서 시작)
korean.DesktopIcon=바탕 화면 바로가기 만들기
korean.LaunchApp=Posture Track 실행
english.AutoStart=Start automatically at Windows sign-in (in the system tray)
english.DesktopIcon=Create a desktop shortcut
english.LaunchApp=Launch Posture Track
[Tasks]
Name: "autostart"; Description: "{cm:AutoStart}"
Name: "desktopicon"; Description: "{cm:DesktopIcon}"
[Files]
Source: "..\dist\PostureTrack\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Posture Track"; Filename: "{app}\PostureTrack.exe"
Name: "{group}\Uninstall Posture Track"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Posture Track"; Filename: "{app}\PostureTrack.exe"; Tasks: desktopicon
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "PostureTrack"; ValueData: """{app}\PostureTrack.exe"" --background"; Tasks: autostart; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "PostureTrack"; Tasks: not autostart; Flags: deletevalue
[Run]
Filename: "{app}\PostureTrack.exe"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent
