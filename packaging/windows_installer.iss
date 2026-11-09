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
; Chromium maps .bin/.pak resources; the default *.exe,*.dll,*.chm misses them.
CloseApplications=yes
CloseApplicationsFilter=*.*
RestartApplications=no
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

[Code]
function UpdateOpenProcess(Access: LongWord; Inherit: Boolean; Pid: LongWord): LongWord;
  external 'OpenProcess@kernel32.dll stdcall';
function UpdateCloseHandle(Handle: LongWord): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';
function UpdateWait(Handle: LongWord; Milliseconds: LongWord): LongWord;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function UpdateTerminate(Handle: LongWord; ExitCode: LongWord): Boolean;
  external 'TerminateProcess@kernel32.dll stdcall';
function UpdateImage(Handle: LongWord; Flags: LongWord; Buffer: String; var Size: LongWord): Boolean;
  external 'QueryFullProcessImageNameW@kernel32.dll stdcall';

function UpdateLongPathName(Source: String; Destination: String; Capacity: LongWord): LongWord;
  external 'GetLongPathNameW@kernel32.dll stdcall';

function UpdateNormalPath(Value: String): String;
var Buffer: String; Size: LongWord;
begin
  Buffer := StringOfChar(#0, 32768);
  Size := UpdateLongPathName(Value, Buffer, 32768);
  if (Size > 0) and (Size < 32768) then Result := Copy(Buffer, 1, Size) else Result := Value;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Locator, Service, Processes, Process: Variant;
  Handles: array of LongWord;
  Handle, Size: LongWord;
  Buffer, Image, Root, EngineRoot: String;
  I, Count: Integer;
  MainRunning: Boolean;
begin
  Result := '';
  Count := 0;
  MainRunning := False;
  Root := AddBackslash(UpdateNormalPath(ExpandConstant('{app}')));
  EngineRoot := Root + '_internal\';
  try
    try
      Locator := CreateOleObject('WbemScripting.SWbemLocator');
      Service := Locator.ConnectServer('', 'root\CIMV2');
      Processes := Service.ExecQuery('SELECT ProcessId FROM Win32_Process WHERE Name=''QtWebEngineProcess.exe'' OR Name=''Stellar Secretary.exe''');
      for I := 0 to Processes.Count - 1 do begin
        Process := Processes.ItemIndex(I);
        Handle := UpdateOpenProcess($00101001, False, Process.ProcessId);
        if Handle <> 0 then begin
          Size := 32768;
          Buffer := StringOfChar(#0, Size);
          Image := '';
          if UpdateImage(Handle, 0, Buffer, Size) then Image := UpdateNormalPath(Copy(Buffer, 1, Size));
          if (CompareText(Image, Root + '{#AppExe}') = 0) and (UpdateWait(Handle, 0) = 258) then MainRunning := True;
          if (CompareText(ExtractFileName(Image), 'QtWebEngineProcess.exe') = 0) and
             (CompareText(Copy(Image, 1, Length(EngineRoot)), EngineRoot) = 0) then begin
            SetArrayLength(Handles, Count + 1);
            Handles[Count] := Handle;
            Count := Count + 1;
          end else UpdateCloseHandle(Handle);
        end;
      end;
      { Leave live main applications to Restart Manager; only orphan engines are handled here. }
      if not MainRunning then begin
        for I := 0 to Count - 1 do begin
          if UpdateWait(Handles[I], 3000) = 258 then begin
            Log('Closing orphan WebEngine from the target installation before file replacement.');
            if not UpdateTerminate(Handles[I], 0) then begin
              Result := 'The old browser subprocess could not exit. Close Stellar Secretary and retry.';
              Exit;
            end;
            if UpdateWait(Handles[I], 5000) <> 0 then begin
              Result := 'The old browser subprocess has not exited. No application files were replaced.';
              Exit;
            end;
          end;
        end;
      end;
    except
      { WMI restrictions must never lead to an unscoped process termination. }
      Log('Orphan WebEngine discovery unavailable: ' + GetExceptionMessage);
    end;
  finally
    for I := 0 to Count - 1 do UpdateCloseHandle(Handles[I]);
  end;
end;
