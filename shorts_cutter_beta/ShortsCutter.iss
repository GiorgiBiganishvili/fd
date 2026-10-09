#define MyAppName "Shorts Cutter Beta"
#define MyAppVersion "0.2.0-beta"
#define MyAppExeName "ShortsCutter.exe"
[Setup]
AppId={{6A87EF41-0B17-4D0D-9D21-22C448F6EF20}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\ShortsCutter
DefaultGroupName={#MyAppName}
OutputDir=dist_installer
OutputBaseFilename=ShortsCutterSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; Flags: unchecked
[Files]
Source: "dist\ShortsCutter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Shorts Cutter"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Shorts Cutter"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить Shorts Cutter"; Flags: nowait postinstall skipifsilent
