; AR-InvestTech installer.
; Build the app first (from the repo root, venv active):
;   pyinstaller packaging/AR-InvestTech.spec
; Then compile this script with Inno Setup (ISCC.exe) — output goes to
; packaging/Output/AR-InvestTech-Setup.exe.
;
; Only the installer itself needs admin (writing to Program Files). The
; installed app never needs to run elevated: it writes exclusively to the
; per-user %LOCALAPPDATA% and HKCU (see src/paths.py, tray.py).

#define MyAppName "AR-InvestTech"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "DippsDev"
#define MyAppExeName "AR-InvestTech.exe"

[Setup]
AppId={{A6E1B6C4-6C0C-4B7E-9C6C-3E6C1F6E9B10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
OutputBaseFilename=AR-InvestTech-Setup
SetupIconFile=ar_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Detect and offer to close a running instance before an in-place upgrade
; (onedir builds have many files a running process can lock).
CloseApplications=yes
CloseApplicationsFilter={#MyAppExeName}
RestartApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "autostart";   Description: "Start {#MyAppName} automatically when Windows starts"; GroupDescription: "Startup:"; Flags: checkedonce

[Files]
Source: "..\dist\AR-InvestTech\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Same HKCU\...\Run value tray.py's own "Start with Windows" toggle writes,
; so the installer's initial choice and the tray icon's later toggle never
; conflict — either can enable/disable the same key.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent

; Uninstall deliberately leaves %LOCALAPPDATA%\AR-InvestTech\ in place —
; settings, license, and MT5 credentials survive a reinstall, same convention
; as most desktop apps. Delete it manually if a clean wipe is ever needed.
