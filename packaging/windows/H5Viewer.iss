; Установщик H5 Viewer собирается Inno Setup на Windows runner.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #error SourceDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif

[Setup]
AppId={{A752F9ED-1C4F-40F8-8B16-259ABAC41E95}
AppName=H5 Viewer
AppVersion={#AppVersion}
AppPublisher=H5 Viewer contributors
AppPublisherURL=https://github.com/fhrnht23/h5_viewer
AppSupportURL=https://github.com/fhrnht23/h5_viewer/issues
DefaultDirName={localappdata}\Programs\H5 Viewer
DefaultGroupName=H5 Viewer
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=H5Viewer-{#AppVersion}-Windows-x86_64-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\H5Viewer.exe
VersionInfoVersion={#AppVersion}
VersionInfoProductName=H5 Viewer
VersionInfoDescription=Two-pane HDF5 viewer and safe editor

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\H5 Viewer"; Filename: "{app}\H5Viewer.exe"
Name: "{autodesktop}\H5 Viewer"; Filename: "{app}\H5Viewer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\H5Viewer.exe"; Description: "{cm:LaunchProgram,H5 Viewer}"; Flags: nowait postinstall skipifsilent
