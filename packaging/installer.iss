; Inno Setup script: dist\AutoVideo-Setup-<version>.exe, from the PyInstaller folder dist\AutoVideo.
; Run through packaging\build.ps1, which passes /DAppVersion from pyproject.toml.
; Installs for the current user only (no administrator rights needed).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F1C2A4E-8B3D-4E7A-9C51-2D7F0B8E4A93}
AppName=AutoVideo
AppVersion={#AppVersion}
AppPublisher=louai
AppPublisherURL=https://github.com/louailou123/AutoVideo
DefaultDirName={autopf}\AutoVideo
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=AutoVideo-Setup-{#AppVersion}
SetupIconFile=..\autovideo\autovideo.ico
UninstallDisplayIcon={app}\AutoVideo.exe
UninstallDisplayName=AutoVideo
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
ShowLanguageDialog=auto
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\AutoVideo\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; a new version replaces the old files instead of mixing with them
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\AutoVideo"; Filename: "{app}\AutoVideo.exe"
Name: "{autodesktop}\AutoVideo"; Filename: "{app}\AutoVideo.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AutoVideo.exe"; Description: "{cm:LaunchProgram,AutoVideo}"; Flags: nowait postinstall skipifsilent
