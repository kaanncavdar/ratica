; Inno Setup script for the Windows installer.
;   iscc /DAppVersion=0.1.0 packaging\windows\ratica.iss
; Installs per user (no administrator rights needed) from dist\Ratica built by PyInstaller.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F1C2B7E-5A43-4E52-9C1D-3B8E7A9F2D41}
AppName=Ratica
AppVersion={#AppVersion}
AppPublisher=Ratica contributors
AppPublisherURL=https://github.com/kaanncavdar/ratica
AppSupportURL=https://github.com/kaanncavdar/ratica/issues
DefaultDirName={localappdata}\Programs\Ratica
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Ratica-{#AppVersion}-Windows-Setup
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\Ratica.exe
LicenseFile=..\..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\..\dist\Ratica\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Ratica"; Filename: "{app}\Ratica.exe"
Name: "{autodesktop}\Ratica"; Filename: "{app}\Ratica.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Ratica.exe"; Description: "Start Ratica"; Flags: nowait postinstall skipifsilent
