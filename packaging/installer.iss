; Inno Setup script for Video Quick Eval (optional installer wrapper).
;
; Prerequisites:
;   1. Run scripts\build_gui_onedir.ps1 successfully
;   2. Install Inno Setup 6: https://jrsoftware.org/isinfo.php
;   3. Open this file in Inno Setup Compiler and Build
;      or:  ISCC.exe packaging\installer.iss
;
; Output: dist\VideoQuickEval-Setup.exe
;
; End-user flow:
;   Double-click Setup.exe → Next → Install → Desktop shortcut → Launch

#define MyAppName "一览成文"
#define MyAppVersion "0.4.5"
#define MyAppPublisher "yilanapp"
#define MyAppExeName "YilanChengWen.exe"
; Project root is parent of packaging\
#define MyProjectRoot ".."
#define MySourceDir MyProjectRoot + "\dist\YilanChengWen"

[Setup]
AppId={{A7C2E9B1-4F3D-4E8A-9C11-VIDEOQUICKEVAL01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\YilanChengWen
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#MyProjectRoot}\dist
OutputBaseFilename=YilanChengWen-Setup
SetupIconFile=app.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
SetupLogging=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
; Keep user data on uninstall? Default removes app dir — warn users to backup config/output
CloseApplications=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked

[Files]
; Entire onedir tree
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Do not overwrite existing user config if reinstalling
Source: "{#MySourceDir}\config.example.json"; DestDir: "{app}"; Flags: ignoreversion
; config.json only if missing
Source: "{#MySourceDir}\config.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\使用说明"; Filename: "{app}\使用说明.txt"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\使用说明.txt"; Description: "打开使用说明"; Flags: postinstall shellexec skipifsilent unchecked

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  if not FileExists(ExpandConstant('{#MySourceDir}\{#MyAppExeName}')) then
  begin
    MsgBox('未找到已构建的程序目录：' + ExpandConstant('{#MySourceDir}') + #13#10 +
           '请先运行 scripts\build_gui_onedir.ps1', mbError, MB_OK);
    Result := False;
  end;
end;
