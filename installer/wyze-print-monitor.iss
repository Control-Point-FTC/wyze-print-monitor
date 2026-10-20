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
; Print watch model: must match failure_model.py (URL, SHA-256, file names).
#define ModelURL "https://www.obico.io/static_pub/ml-models/model-weights-5a6b1be1fa.onnx"
#define ModelSHA256 "0a6ebd8e30dbf6a450c50f9c0a5406f04ba7eb1c99fd5996e888c78bb383b9aa"
#define ModelDir "{userappdata}\wyze-print-monitor\models"
#define ModelFile "obico-failure-detection.onnx"
#define ModelEnableMarker "enable-print-watch"

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
; Short, friendly flow: Welcome -> shortcut option -> install -> done
; (no folder, license or "ready" pages).
DisableWelcomePage=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
; New installs default to "just me" (no admin). The choice stays available so
; an existing all-users install is upgraded in place: with
; UsePreviousPrivileges, Setup reuses the previous install mode and doesn't
; ask on upgrades (silent updates included).
PrivilegesRequiredOverridesAllowed=dialog
UsePreviousPrivileges=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\build\installer
OutputBaseFilename=WyzePrintMonitor-{#AppVersion}-setup
SetupIconFile=..\src\wyze_print_monitor\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
; Windows 11 look, light or dark following the user's Windows theme.
WizardStyle=modern dynamic windows11
; Transparent PNGs from packaging/make_artwork.py for 100-250% DPI; Setup
; picks the size that best fits the screen.
WizardImageFile=wizard-side-202.png,wizard-side-269.png,wizard-side-336.png,wizard-side-430.png,wizard-side-534.png
WizardSmallImageFile=wizard-logo-58.png,wizard-logo-73.png,wizard-logo-87.png,wizard-logo-116.png,wizard-logo-145.png
Compression=lzma2/max
SolidCompression=yes
; Close a running copy before replacing its files (and on uninstall).
AppMutex={#AppMutexName}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nWatch and control the Wyze Cam on your 3D printer (live view, snapshots, recordings and timelapses) right inside eufyMake Studio, with an optional AI that watches for failed prints.%n%nNo admin rights needed.
FinishedLabel=[name] is installed. Find it any time in the Start menu: just search for "Wyze".

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; Offered only when the model isn't there yet; never inherited by updates
; (a silent update must not start a 200 MB download).
Name: "aimodel"; Description: "Download the AI print-failure model (about 200 MB) and turn on Print watch"; GroupDescription: "Print watch: alerts you to failed prints and can pause them (optional, runs on this PC; model by Obico, AGPL-3.0):"; Flags: dontinheritcheck; Check: ShouldOfferModel

[Files]
Source: "..\build\dist\WyzePrintMonitor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[InstallDelete]
; Updates replace the whole app folder, so files dropped by a newer
; PyInstaller/Qt can't linger next to the old ones.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
; The Start menu entry is what makes the app show up in Windows search.
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[UninstallDelete]
; The downloaded model (settings stay, like the rest of the user's data).
Type: filesandordirs; Name: "{#ModelDir}"

[Registry]
; The app can add itself to startup (Settings → Launch at startup);
; remove that entry when the app is uninstalled.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "WyzePrintMonitor"; Flags: uninsdeletevalue

[Run]
; Normal install: offer to launch on the last page.
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; Silent install = in-app update: reopen the app automatically.
Filename: "{app}\{#AppExe}"; Flags: nowait skipifnotsilent

[Code]
var
  DownloadPage: TDownloadWizardPage;
  ModelDownloaded: Boolean;
  ModelError: String;

function ModelPath(): String;
begin
  Result := ExpandConstant('{#ModelDir}\{#ModelFile}');
end;

function ShouldOfferModel(): Boolean;
begin
  // Interactive installs offer it; silent ones (in-app updates) only when
  // asked for explicitly with /aimodel=1.
  Result := (not FileExists(ModelPath())) and
    ((not WizardSilent()) or (ExpandConstant('{param:aimodel|0}') = '1'));
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard();
begin
  DownloadPage := CreateDownloadPage('Downloading the AI model',
    'Getting the print-failure model from Obico and checking it. You can skip this and download it later in Settings > Print watch.',
    @OnDownloadProgress);
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
end;

// Interactive: download right after the options page, with a progress bar.
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectTasks) and WizardIsTaskSelected('aimodel') and not ModelDownloaded then
  begin
    DownloadPage.Clear;
    DownloadPage.Add('{#ModelURL}', '{#ModelFile}', '{#ModelSHA256}');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;  // verifies the SHA-256
        ModelDownloaded := True;
      except
        if DownloadPage.AbortedByUser then
          ModelError := 'The download was cancelled.'
        else
          ModelError := GetExceptionMessage;
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

procedure InstallModel();
var
  Dir: String;
begin
  Dir := ExpandConstant('{#ModelDir}');
  ForceDirectories(Dir);
  if FileCopy(ExpandConstant('{tmp}\{#ModelFile}'), ModelPath(), False) then
    // The app turns Print watch on when it sees this (and removes it).
    SaveStringToFile(Dir + '\{#ModelEnableMarker}', 'from installer', False)
  else
    ModelError := 'Could not save the model to ' + Dir + '.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('aimodel') then
  begin
    if (not ModelDownloaded) and (ModelError = '') then
    begin
      // Silent installs (/aimodel=1) never saw the page: download quietly.
      try
        DownloadTemporaryFile('{#ModelURL}', '{#ModelFile}', '{#ModelSHA256}', @OnDownloadProgress);
        ModelDownloaded := True;
      except
        ModelError := GetExceptionMessage;
      end;
    end;
    if ModelDownloaded then
      InstallModel();
    if ModelError <> '' then
      SuppressibleMsgBox('The app is installed, but the AI model could not be downloaded:' + #13#10 + ModelError +
        #13#10#13#10 + 'You can download it any time in Settings > Print watch.', mbInformation, MB_OK, IDOK);
  end;
end;
