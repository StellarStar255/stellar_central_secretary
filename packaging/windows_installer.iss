; Inno Setup script for the Windows installer (per-user install, no admin rights).
; Built by .github/workflows/release.yml:  iscc /DAppVersion=0.1.0 packaging\windows_installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "知识秘书"
#define AppExe "Stellar Secretary.exe"

[Setup]
AppId={{82341F5D-5A3C-4A10-926C-5321B74C1827}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Stellar Secretary
AppPublisherURL=https://github.com/StellarStar255/stellar_central_secretary
DefaultDirName={localappdata}\Programs\Stellar Secretary
DefaultGroupName={#AppName}
UsePreviousGroup=no
PrivilegesRequired=lowest
MinVersion=10.0.17763
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=..\dist
OutputBaseFilename=Stellar-Secretary-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Stellar Secretary\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; User data in %LOCALAPPDATA%\Stellar Secretary is preserved on uninstall.
