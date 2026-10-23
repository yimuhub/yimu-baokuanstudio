; ==============================================================================
;  一幕·YIMU 爆款工作室 (YIMU Studio) - Windows 原生应用安装程序 (.exe)
;  基于 Inno Setup 6 构建，生成标准现代化 Windows Setup 安装包
; ==============================================================================

#define MyAppName "一幕·YIMU 爆款工作室"
#define MyAppVersion "10.2.1"
#define MyAppPublisher "YIMU Studio Team"
#define MyAppURL "https://yimu.hyipf.com"
#define MyAppExeName "一幕桌面客户端.vbs"

[Setup]
; 唯一 GUID 标识应用程序
AppId={{D37E6F1A-B82C-4A59-8F72-1E5A9D3F4C82}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\YIMU-Studio
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\..\dist
OutputBaseFilename=YIMU-Studio-Windows-Setup-v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
DisableProgramGroupPage=auto
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; 打包源码、资源以及嵌入式 Python runtime
Source: "..\..\dist\bundle_win\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "wscript.exe"; Parameters: """{app}\一幕桌面客户端.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\web\static\favicon.ico"
Name: "{group}\一键启动(调试控制台)"; Filename: "{app}\一键启动.bat"; WorkingDir: "{app}"
Name: "{group}\一键升级助手"; Filename: "{app}\一键升级.bat"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "wscript.exe"; Parameters: """{app}\一幕桌面客户端.vbs"""; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\web\static\favicon.ico"

[Run]
Filename: "wscript.exe"; Parameters: """{app}\一幕桌面客户端.vbs"""; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
