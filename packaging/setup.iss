; CallName 安装脚本（Inno Setup 6+）。
;
; 编译（Windows 上）：
;     ISCC.exe /DAppVersion=2.2.0 packaging\setup.iss
; 产物在 dist\installer\CallName-Setup-<版本>.exe
;
; 安装范围只针对当前用户（PrivilegesRequired=lowest），不弹 UAC，装到
; %LOCALAPPDATA% 下，并且**不允许**临时提升为管理员安装（见下方
; PrivilegesRequired 附近的说明）。
;
; 数据：callname.db 由程序自己在 exe 旁边生成，**不随安装包分发**。
; Inno 卸载时只删安装日志里记下的文件，所以名单库与日志会留在
; %LOCALAPPDATA%\CallName 下；这是刻意的——名单是老师攒出来的，
; 不能因为卸载/重装就丢。想彻底清干净，卸载后手动删这个目录。
;
; 注意：本文件里所有相对路径都相对**本文件所在目录**（packaging/）解析。
;
; 版本号：CI 会用 /DAppVersion=<pyproject.toml 的 version> 传进来；本机手打时
; 不传则用下面的默认值。

#define AppName "CallName"
; 用户能看到的名字：所有快捷方式、启动项、安装/卸载界面都用它。
; 与 AppName 分开是因为 AppName 还决定安装目录，改了会让老版本升级断链
; （见下方 AppId 的说明）。
#define AppDisplayName "随机点名器"
#define AppExeName "CallName.exe"

#ifndef AppVersion
  #define AppVersion "2.2.0"
#endif

; spec 生成的目录名与仓库根同级，即 <仓库>/dist/CallName
#define BuildDir "..\dist\CallName"

[Setup]
; AppId 唯一标识本软件。**一旦发布就不要再改**，否则新版本会被当成另一个
; 程序，覆盖安装与卸载都会错乱。这是 CallName 的首个安装包，此值是新建的。
AppId={{dd63adf4-460c-452e-b1ad-75dc2c27ac2e}}
AppName={#AppDisplayName}
AppVersion={#AppVersion}
AppVerName={#AppDisplayName} {#AppVersion}
DefaultDirName={localappdata}\{#AppName}
DisableDirPage=yes
DefaultGroupName={#AppDisplayName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
; 刻意不设 PrivilegesRequiredOverridesAllowed：安装目录在 %LOCALAPPDATA% 下、
; 用户可写，而卸载时会经 powershell 执行 {app} 里的 killapp.ps1。一旦允许
; 临时改成管理员安装/卸载，就等于给任何能写这个目录的人一个提权执行点。
; 只允许当前用户安装就没有这个问题。
OutputDir=..\dist\installer
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 图标沿用仓库根的 icon.ico（已是多尺寸 ico，见 packaging/README.md）
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}

; 界面语言：Inno 官方不带简体中文语言文件，直连会让 ISCC 报
; "Could not read language file" 而构建失败，所以默认只用英文向导。
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: checkedonce
; 不做开机自启：点名器只在课堂上用，常驻后台没有意义。
; 需要的话用户自己把快捷方式拖进「启动」文件夹。

[Files]
; 结束进程用的小脚本（见下方 KillApp）。以 dontcopy 编进安装器本体，安装时
; 解压到临时目录用。必须放在 [Files] 最前面：SolidCompression 下，取靠后的
; 文件要先把前面的全部解压到内存。
Source: "killapp.ps1"; Flags: dontcopy noencryption
; 程序本体。**排除掉运行期数据**：本机先跑过一遍再打包时，dist\CallName 里
; 会有 callname.db / callname.log，绝不能装进用户目录覆盖真实名单。
; 升级时也不覆盖数据库——它根本不在安装包里。
Source: "{#BuildDir}\*"; DestDir: "{app}"; Excludes: "callname.db,callname.db-wal,callname.db-shm,callname.log,callname.log.*"; Flags: ignoreversion recursesubdirs createallsubdirs
; 再装一份到 {app}，卸载器要用它结束本程序的进程（见 CurUninstallStepChanged）
Source: "killapp.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\{#AppDisplayName}\{#AppDisplayName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExeName}"
Name: "{userprograms}\{#AppDisplayName}\卸载 {#AppDisplayName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\{#AppExeName}"
Name: "{userdesktop}\{#AppDisplayName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\{#AppExeName}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "立即运行 {#AppDisplayName}"; Flags: postinstall nowait skipifsilent unchecked

[Code]
{ 圆形图标窗口在 Inno 的 Restart Manager 下不一定能被识别，不主动杀进程就会
  因为 exe（及 SQLite 文件）被占用而装不上。

  不能用 taskkill /im：它按进程映像名匹配，机器上任何同名程序都会被一起
  强杀。killapp.ps1 按可执行文件的完整路径过滤，只结束本安装目录下的那个
  进程；没在跑时什么也不做，返回码忽略。 }
procedure KillApp(const ExePath: String);
var
  ResultCode: Integer;
begin
  ExtractTemporaryFile('killapp.ps1');
  Exec('powershell.exe',
       '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
       ExpandConstant('{tmp}\killapp.ps1') + '" -ExePath "' + ExePath + '"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure KillRunningApp;
begin
  KillApp(ExpandConstant('{app}\{#AppExeName}'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillRunningApp;
  Result := '';
end;

{ 卸载时结束本程序的进程。走 CurUninstallStepChanged 而不是 UninstallRun 段：
  那个段没法按条件跳过，而这里必须能判断"当前是否提权"。

  killapp.ps1 装在安装目录下，用户可写。正常情况下卸载器以当前用户运行，替换
  它没有任何收益；但如果用户手动右键"以管理员身份运行"卸载器，执行用户可写
  的脚本就成了提权执行点，所以提权时直接跳过——文件被占用时 Inno 会提示重启。

  刻意**不删** callname.db / callname.log：名单与累计次数是用户数据，
  卸载重装后还要接着用（见文件头）。 }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
  Script: String;
begin
  if CurUninstallStep <> usUninstall then
    Exit;

  Script := ExpandConstant('{app}\killapp.ps1');
  if (not IsAdmin) and FileExists(Script) then
    Exec('powershell.exe',
         '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + Script +
         '" -ExePath "' + ExpandConstant('{app}\{#AppExeName}') + '"',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;
