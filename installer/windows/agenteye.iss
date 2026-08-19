; Inno Setup script for Agent Eye (Windows)
;
; Builds an installer that:
;   - Installs Agent Eye (PyInstaller bundle) to the user's local app data folder
;   - Creates a Start Menu shortcut that launches the system tray app
;   - Registers the app in Add/Remove Programs for clean uninstall
;
; Build with Inno Setup 6+:
;   ISCC.exe installer\windows\agenteye.iss
;
; Expected inputs (defined on command line or via environment):
;   MyAppVersion  — version string, e.g. 1.3.0
;   DistDir       — path to the PyInstaller dist\AgentEye\ directory
;
; These can be overridden with /D<name>=<value> on the ISCC command line.

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#ifndef DistDir
  #define DistDir "..\..\dist\AgentEye"
#endif

#define MyAppName "Agent Eye"
#define MyAppPublisher "Jeff Steinbok"
#define MyAppURL "https://github.com/JeffSteinbok/agenteye"
#define MyAppExeName "AgentEye.exe"
#define MyAppId "{{A2B4C6D8-E0F2-4A6C-8E0A-2C4E6F8A0C2E}"

[Setup]
; NOTE: The value of AppId uniquely identifies this application.
; Do not use the same AppId value in installers for other applications.
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
; Install per-user so no elevation is required
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={userpf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; Output
OutputDir=..\..\dist\installer
OutputBaseFilename=AgentEyeSetup-{#MyAppVersion}
; Icon shown in Add/Remove Programs
UninstallDisplayIcon={app}\{#MyAppExeName}
; Compression
Compression=lzma2/ultra64
SolidCompression=yes
; Architecture
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Appearance
WizardStyle=modern
; Minimum OS: Windows 10
MinVersion=10.0.17763
; No console window during install
WindowVisible=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startmenuicon"; Description: "Create a Start Menu shortcut"; GroupDescription: "Shortcuts:"; Flags: checked
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "autostart"; Description: "Start Agent Eye automatically when I log in"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; Copy the entire PyInstaller output directory
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu shortcut — launches the tray app (no console window)
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "app"; \
  Comment: "Open the Agent Eye dashboard"; \
  Tasks: startmenuicon

; Desktop shortcut (optional)
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "app"; \
  Comment: "Open the Agent Eye dashboard"; \
  Tasks: desktopicon

; Uninstall entry in Start Menu
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Registry]
; Optional autostart: launch the tray app on login (hidden so only tray icon appears)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "AgentEye"; \
  ValueData: """{app}\{#MyAppExeName}"" app --hidden"; \
  Flags: uninsdeletevalue; Tasks: autostart

[Run]
; Offer to launch the app after installation completes
Filename: "{app}\{#MyAppExeName}"; Parameters: "app"; \
  Description: "Launch {#MyAppName} now"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
; Remove the autostart registry entry on uninstall (if present)
Filename: "reg.exe"; \
  Parameters: "delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v AgentEye /f"; \
  Flags: runhidden; RunOnceId: "RemoveAutostart"

[Code]
// Inno Setup Pascal script — no custom code needed for this installer.
// Placeholder retained for future extensibility.
