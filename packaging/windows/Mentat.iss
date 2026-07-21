#define MyAppName "Mentat"
#define MyAppPublisher "Mentat"
#define MyAppExeName "Mentat Launcher.exe"

#ifndef MyAppVersion
  #error MyAppVersion must be supplied by scripts/build_native.py
#endif
#ifndef MyAppSourceDir
  #error MyAppSourceDir must be supplied by scripts/build_native.py
#endif
#ifndef MyAppOutputDir
  #error MyAppOutputDir must be supplied by scripts/build_native.py
#endif

[Setup]
AppId={{7A4E3D1B-6349-4B50-936E-438DDBB91A72}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Mentat
DefaultGroupName=Mentat
DisableProgramGroupPage=yes
OutputDir={#MyAppOutputDir}
OutputBaseFilename=Mentat-{#MyAppVersion}-windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}
; Operator data lives outside {app}. The uninstaller removes application files
; only and intentionally leaves Mentat data untouched.

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Operator data is always external, so remove stale application files before
; laying down a new version. This prevents old bundled code surviving upgrade.
Type: filesandordirs; Name: "{app}\*"

[Icons]
Name: "{autoprograms}\Mentat"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Mentat"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Open Mentat"; Flags: nowait postinstall skipifsilent
