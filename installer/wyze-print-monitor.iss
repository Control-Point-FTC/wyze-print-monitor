; Inno Setup script for the Wyze Print Monitor Windows installer.
;
; Built by packaging/build_windows.py (and the Release workflow) after
; PyInstaller has produced build\dist\WyzePrintMonitor\. Compile by hand with:
;   iscc /DAppVersion=1.0.0 installer\wyze-print-monitor.iss
;
; Per-user install (no admin / UAC prompt) into %LOCALAPPDATA%\Programs, so
; the in-app updater can run a new installer silently.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Wyze Print Monitor"
#define AppExe "WyzePrintMonitor.exe"
#define AppPublisher "Control Point FTC"
#define AppURL "https://github.com/Control-Point-FTC/wyze-print-monitor"
; Must match APP_USER_MODEL_ID / INSTALLER_MUTEX in src/wyze_print_monitor/app.py.
#define AppUserModelID "ControlPointFTC.WyzePrintMonitor"
#define AppMutexName "WyzePrintMonitorRunning"

[Setup]
; Never change AppId: it's how upgrades and the uninstaller find the install.
AppId={{6F4C2E3A-8B1D-4E7A-9C52-1D3B8A7F0E64}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases/latest
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE
OutputDir=..\build\installer
OutputBaseFilename=WyzePrintMonitor-{#AppVersion}-setup
SetupIconFile=..\src\wyze_print_monitor\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=wizard-large-164.bmp,wizard-large-328.bmp
WizardSmallImageFile=wizard-small-55.bmp,wizard-small-69.bmp,wizard-small-110.bmp
Compression=lzma2/max
SolidCompression=yes
; Close a running copy before replacing its files (and on uninstall).
AppMutex={#AppMutexName}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\build\dist\WyzePrintMonitor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Updates replace the whole app folder, so files dropped by a newer
; PyInstaller/Qt can't linger next to the old ones.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
; The Start menu entry is what makes the app show up in Windows search.
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Registry]
; The app can add itself to startup (Settings → Launch at startup);
; remove that entry when the app is uninstalled.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "WyzePrintMonitor"; Flags: uninsdeletevalue

[Run]
; Normal install: offer to launch on the last page.
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; Silent install = in-app update: reopen the app automatically.
Filename: "{app}\{#AppExe}"; Flags: nowait skipifnotsilent
