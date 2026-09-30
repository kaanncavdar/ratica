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

[Code]
{ On uninstall, offer to delete what Ratica downloaded (engine and AI model, several GB) and its settings.
  Translated books live next to the user's PDFs and are never touched. Silent uninstalls keep the files. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\Ratica');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox('Also delete the translation engine and AI model that Ratica downloaded (about 5-6 GB)?' + #13#10#13#10 +
                'Your PDFs and translated books are not affected.', mbConfirmation, MB_YESNO) = IDYES then
      begin
        DelTree(DataDir, True, True, True);
        RegDeleteKeyIncludingSubkeys(HKEY_CURRENT_USER, 'Software\Ratica');
      end;
  end;
end;
