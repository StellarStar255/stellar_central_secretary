; Inno Setup script for the Windows installer (per-user install, no admin rights).
; Built by .github/workflows/release.yml:  iscc /DAppVersion=0.1.0 packaging\windows_installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "知识秘书"
#define AppExe "Stellar Secretary.exe"

[Setup]
#ifdef UpdateSmokeTest
AppId=StellarSecretaryWindowsUpdateSmokeTest
#else
AppId={{82341F5D-5A3C-4A10-926C-5321B74C1827}
#endif
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Stellar Secretary
AppPublisherURL=https://github.com/StellarStar255/stellar_central_secretary
DefaultDirName={localappdata}\Programs\Stellar Secretary
UsePreviousAppDir=yes
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

#ifndef UpdateSmokeTest
[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
#endif

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#AppExe}"; Flags: nowait skipifnotsilent; Check: ShouldLaunchSilentUpgrade

; Library and backup directories are managed by the app and preserved on uninstall.

[UninstallDelete]
Type: files; Name: "{app}\.stellar-installed-version"

[Code]
var
  ExistingInstallation: Boolean;
  ResourceDirectory, StagedResources: String;
  InstallationComplete: Boolean;

function ShouldLaunchSilentUpgrade: Boolean;
var
  I: Integer;
begin
  Result := ExistingInstallation;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/NORESTARTAPPLICATIONS') = 0 then Result := False;
end;

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
function UpdateProcessId: LongWord;
  external 'GetCurrentProcessId@kernel32.dll stdcall';

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
  ExistingInstallation := FileExists(ExpandConstant('{app}\{#AppExe}'));
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
      if MainRunning then begin
        Result := 'Stellar Secretary is still running. Exit it before installing the update.';
        Exit;
      end;
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
    except
      { WMI restrictions must never lead to an unscoped process termination. }
      Log('Orphan WebEngine discovery unavailable: ' + GetExceptionMessage);
    end;
  finally
    for I := 0 to Count - 1 do UpdateCloseHandle(Handles[I]);
  end;
  if not ExistingInstallation or (StagedResources <> '') then Exit;
  ResourceDirectory := EngineRoot + 'PySide6\resources';
  if not DirExists(ResourceDirectory) then Exit;
  { The old updater's file probe can pass before a transient lock appears.
    Set the resources aside before Setup starts replacing program files. }
  Buffer := Root + '.stellar-webengine-resources-' + IntToStr(UpdateProcessId);
  for I := 0 to 80 do begin
    if RenameFile(ResourceDirectory, Buffer) then begin
      StagedResources := Buffer;
      Log('Moved old WebEngine resources aside before installation.');
      Exit;
    end;
    if I = 0 then Log('Waiting for old WebEngine resource handles to close.');
    if I < 80 then Sleep(250);
  end;
  Result := 'The old browser resources are still in use. No application files were replaced.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    InstallationComplete := True;
    if not SaveStringToFile(ExpandConstant('{app}\.stellar-installed-version'), '{#AppVersion}', False) then
      Log('Could not record the installed version.');
  end;
end;

procedure DeinitializeSetup;
begin
  if StagedResources = '' then Exit;
  if InstallationComplete then begin
    if not DelTree(StagedResources, True, True, True) then
      Log('Old WebEngine resources retained at ' + StagedResources);
  end else begin
    if DirExists(ResourceDirectory) then
      if not RenameFile(ResourceDirectory, StagedResources + '.incomplete') then begin
        Log('Could not move incomplete resources; old resources retained at ' + StagedResources);
        Exit;
      end;
    if not RenameFile(StagedResources, ResourceDirectory) then
      Log('Could not restore old resources; retained at ' + StagedResources);
  end;
end;
