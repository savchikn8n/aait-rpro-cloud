; Установщик ИИ-агента для R-Pro.
;
; Собирается скриптом installer\build.ps1 — он готовит папку stage и передаёт
; сюда версию. Руками: ISCC /DVersion=1.2.3 /DStage=stage rpro-agent.iss
;
; Что куда ставится
; -----------------
; Всё, кроме загрузчика, ставится в профиль пользователя и прав
; администратора не требует:
;
;   %LOCALAPPDATA%\Programs\AAIT\RProAgent\
;       python\          встраиваемый Python с библиотеками агента
;       agent\           сервер агента (serve.py) и defaults.json с адресом
;                        сервера моделей
;       core\<версия>\   ядро плагина: тикер, окно чата, автозапуск агента
;       loader\          копия загрузчика, из неё он кладётся в папку R-Pro
;       bridge\          копия моста для переустановки
;   Документы\R-Pro\<версия R-Pro>\My Commands\AIAgentBridge\   мост
;   HKCU\Software\AAIT\RProAgent    где всё это лежит (читает загрузчик)
;
; Загрузчик (Plugin.AiBridge.dll) должен лежать в папке R-Pro в Program
; Files — только оттуда программа берёт плагины. Для этого установщик один
; раз просит права администратора. Загрузчик меняется редко, поэтому
; обновления обычно ставятся без прав администратора.
;
; Почему установщик не просит права администратора целиком: тогда
; «Документы» и HKCU оказались бы того, кто ввёл пароль администратора, а не
; того, кто работает в R-Pro.

#ifndef Version
  #error Передайте версию: ISCC /DVersion=1.2.3
#endif
#ifndef Stage
  #define Stage "stage"
#endif

#define AppName "ИИ-агент для R-Pro"
#define RegKey "Software\AAIT\RProAgent"

[Setup]
AppId={{8C1B6F0E-4F7A-4B7E-9E61-5B2E3A7F9D10}
AppName={#AppName}
AppVersion={#Version}
AppVerName={#AppName} {#Version}
AppPublisher=ИТЦ Автотор
AppPublisherURL=https://rpro.itc.kl.avtotor.ru/
AppSupportURL=https://rpro.itc.kl.avtotor.ru/
VersionInfoVersion={#Version}
DefaultDirName={userpf}\AAIT\RProAgent
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=rpro-agent-setup-{#Version}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}
SetupLogging=yes
; Второй установщик, пока первый ждёт закрытия R-Pro, не нужен.
SetupMutex=AAIT.RProAgent.Setup
ShowLanguageDialog=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Messages]
ru.WelcomeLabel2=Будет установлен [name/ver].%n%nАгент встраивается в R-Pro: справа появится панель «ИИ-агент», где можно спрашивать о сцене, компонентах и симуляции.%n%nПеред установкой закройте R-Pro.
ru.FinishedLabel=Установка завершена. Запустите R-Pro — панель «ИИ-агент» появится справа.

[InstallDelete]
; Прошлые версии ядра и агента убираем целиком: в папках не должно
; оставаться файлов, которых нет в новой версии.
Type: filesandordirs; Name: "{app}\core"
Type: filesandordirs; Name: "{app}\agent"
Type: filesandordirs; Name: "{app}\bridge"
; Скомпилированный Python от прошлой версии моста только мешает.
Type: files; Name: "{code:BridgeDir}\*.pyc"; Check: HasBridgeDir

[Files]
Source: "{#Stage}\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs ignoreversion
Source: "{#Stage}\agent\*"; DestDir: "{app}\agent"; Flags: recursesubdirs ignoreversion
Source: "{#Stage}\core\AiBridge.Core.dll"; DestDir: "{app}\core\{#Version}"; Flags: ignoreversion
Source: "{#Stage}\loader\Plugin.AiBridge.dll"; DestDir: "{app}\loader"; Flags: ignoreversion
Source: "{#Stage}\bridge\AIAgentBridge\*"; DestDir: "{app}\bridge\AIAgentBridge"; Flags: recursesubdirs ignoreversion
; Мост — в папку команд R-Pro. Настроенный пользователем bridge.json не трогаем.
Source: "{#Stage}\bridge\AIAgentBridge\*"; DestDir: "{code:BridgeDir}"; Excludes: "bridge.json"; Flags: recursesubdirs ignoreversion; Check: HasBridgeDir
Source: "{#Stage}\bridge\AIAgentBridge\bridge.json"; DestDir: "{code:BridgeDir}"; Flags: onlyifdoesntexist; Check: HasBridgeDir

[Registry]
Root: HKCU; Subkey: "{#RegKey}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "{#RegKey}"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"
Root: HKCU; Subkey: "{#RegKey}"; ValueType: string; ValueName: "Version"; ValueData: "{#Version}"
Root: HKCU; Subkey: "{#RegKey}"; ValueType: string; ValueName: "CorePath"; ValueData: "{app}\core\{#Version}\AiBridge.Core.dll"

[UninstallDelete]
; Python и агент накапливают __pycache__, которого нет в журнале установки.
Type: filesandordirs; Name: "{app}"

[Code]
const
  RProProcess = 'rpro_starter.exe';
  LoaderName = 'Plugin.AiBridge.dll';
  { Имя плагина из самой первой версии, когда он умел только тикать. }
  LegacyName = 'Plugin.AiBridgeTicker.dll';
  ErrorCancelled = 1223;

var
  RProDir: String;
  BridgeTarget: String;

{ Самая новая из папок, подходящих под маску, или пустая строка. }
function NewestDir(const Parent, Mask: String): String;
var
  Rec: TFindRec;
begin
  Result := '';
  if FindFirst(AddBackslash(Parent) + Mask, Rec) then
  try
    repeat
      if (Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0) and
         (Rec.Name <> '.') and (Rec.Name <> '..') and
         (CompareText(Rec.Name, Result) > 0) then
        Result := Rec.Name;
    until not FindNext(Rec);
  finally
    FindClose(Rec);
  end;
  if Result <> '' then
    Result := AddBackslash(Parent) + Result;
end;

function FindRPro: String;
begin
  Result := NewestDir(ExpandConstant('{commonpf32}'), 'RProv*');
  if (Result = '') and IsWin64 then
    Result := NewestDir(ExpandConstant('{commonpf64}'), 'RProv*');
end;

{ Папка команд R-Pro: Документы\R-Pro\<версия>\My Commands. Её создаёт сама
  программа при первом запуске, поэтому без запуска её может не быть. }
function FindBridgeDir: String;
var
  VersionDir: String;
begin
  Result := '';
  VersionDir := NewestDir(ExpandConstant('{userdocs}\R-Pro'), '*');
  if VersionDir <> '' then
    Result := VersionDir + '\My Commands\AIAgentBridge';
end;

function BridgeDir(Param: String): String;
begin
  Result := BridgeTarget;
end;

function HasBridgeDir: Boolean;
begin
  Result := BridgeTarget <> '';
end;

function IsRProRunning: Boolean;
var
  Locator, Service, Found: Variant;
begin
  Result := False;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    Found := Service.ExecQuery(
      'SELECT ProcessId FROM Win32_Process WHERE Name = ''' + RProProcess + '''');
    Result := Found.Count > 0;
  except
    { Не смогли спросить — не мешаем установке. Занятый файл Inno покажет сам. }
  end;
end;

{ R-Pro держит ядро и Python агента занятыми, пока открыта. В обычном
  режиме просим её закрыть. В тихом ждём, пока закроется сама: две минуты,
  а с ключом /WAITFORRPRO=1 — сколько угодно. С этим ключом установщик
  запускает панель агента, когда пользователь нажал «Обновить»: обновление
  ставится, как только он закончит работу и закроет R-Pro. }
function WaitForever: Boolean;
begin
  Result := ExpandConstant('{param:WAITFORRPRO|0}') = '1';
end;

function WaitForRProClosed: Boolean;
var
  Waited: Integer;
begin
  Result := True;
  Waited := 0;
  while IsRProRunning do
  begin
    if WizardSilent then
    begin
      if (Waited >= 60) and not WaitForever then
      begin
        Log('R-Pro так и не закрылась за две минуты, обновление отменено.');
        Result := False;
        Exit;
      end;
      Sleep(2000);
      Waited := Waited + 1;
    end
    else if MsgBox('R-Pro сейчас открыта. Закройте её и нажмите «Повторить».',
                   mbError, MB_RETRYCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
  end;
end;

function InitializeSetup: Boolean;
begin
  Result := False;

  RProDir := FindRPro;
  if RProDir = '' then
  begin
    SuppressibleMsgBox('Не найдена установленная R-Pro (папка RProv* в Program Files).' + #13#10 +
      'Сначала установите R-Pro, затем запустите этот установщик снова.',
      mbCriticalError, MB_OK, IDOK);
    Exit;
  end;
  Log('R-Pro: ' + RProDir);

  if not WaitForRProClosed then
    Exit;

  BridgeTarget := FindBridgeDir;
  Log('Мост: ' + BridgeTarget);
  Result := True;
end;

{ Выполняет команду cmd с правами администратора. Windows покажет запрос UAC. }
function RunElevated(const Command: String; var Code: Integer): Boolean;
begin
  Result := ShellExec('runas', ExpandConstant('{cmd}'), '/s /c "' + Command + '"',
                      '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

{ Версия загрузчика из свойств файла. Байты сравнивать бесполезно:
  компилятор .NET Framework при каждой сборке выдаёт другие. }
function LoaderVersion(const FileName: String): String;
begin
  if not FileExists(FileName) or not GetVersionNumbersString(FileName, Result) then
    Result := '';
end;

function SameFile(const A, B: String): Boolean;
begin
  Result := FileExists(A) and FileExists(B) and
            (GetSHA256OfFile(A) = GetSHA256OfFile(B));
end;

procedure InstallLoader;
var
  Source, Target, Legacy, Command: String;
  Code: Integer;
begin
  Source := ExpandConstant('{app}\loader\') + LoaderName;
  Target := AddBackslash(RProDir) + LoaderName;
  Legacy := AddBackslash(RProDir) + LegacyName;

  if (LoaderVersion(Source) <> '') and (LoaderVersion(Source) = LoaderVersion(Target)) and
     not FileExists(Legacy) then
  begin
    Log('Загрузчик в папке R-Pro уже версии ' + LoaderVersion(Target) + '.');
    Exit;
  end;

  SuppressibleMsgBox('Сейчас Windows попросит права администратора.' + #13#10#13#10 +
    'Они нужны, чтобы положить небольшой файл-загрузчик в папку R-Pro — ' +
    'только оттуда программа подключает дополнения. Обычно это делается ' +
    'один раз, обновления агента ставятся без прав администратора.',
    mbInformation, MB_OK, IDOK);

  Command := 'copy /y "' + Source + '" "' + Target + '"';
  if FileExists(Legacy) then
    Command := 'del /f /q "' + Legacy + '" & ' + Command;

  if not RunElevated(Command, Code) or not SameFile(Source, Target) then
  begin
    if Code = ErrorCancelled then
      Log('Пользователь отказался давать права администратора.')
    else
      Log('Загрузчик не скопирован, код ' + IntToStr(Code));
    SuppressibleMsgBox('Не удалось положить загрузчик в папку R-Pro, без него агент не появится.' + #13#10#13#10 +
      'Запустите установщик ещё раз и разрешите изменения, либо попросите администратора скопировать файл' + #13#10 +
      Source + #13#10 + 'в папку' + #13#10 + RProDir,
      mbError, MB_OK, IDOK);
  end
  else
    Log('Загрузчик установлен: ' + Target);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then
    Exit;

  InstallLoader;

  if BridgeTarget = '' then
    SuppressibleMsgBox('R-Pro ещё ни разу не запускалась под вашей учётной записью, ' +
      'поэтому мост для неё поставить некуда.' + #13#10#13#10 +
      'Запустите R-Pro один раз, закройте её и запустите этот установщик снова.',
      mbInformation, MB_OK, IDOK);
end;

function InitializeUninstall: Boolean;
begin
  Result := False;
  RProDir := FindRPro;
  while IsRProRunning do
    if MsgBox('R-Pro сейчас открыта. Закройте её и нажмите «Повторить».',
              mbError, MB_RETRYCANCEL) = IDCANCEL then
      Exit;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Target: String;
  Code: Integer;
begin
  if (CurUninstallStep <> usPostUninstall) or (RProDir = '') then
    Exit;

  { Без ядра загрузчик безвреден — он только покажет, что агент не
    установлен. Но оставлять его незачем, поэтому просим права и убираем. }
  Target := AddBackslash(RProDir) + LoaderName;
  if FileExists(Target) then
    if not RunElevated('del /f /q "' + Target + '"', Code) or FileExists(Target) then
      MsgBox('Не удалось убрать загрузчик из папки R-Pro. Удалите вручную файл' + #13#10 + Target,
             mbInformation, MB_OK);
end;
