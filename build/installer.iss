; 天学网单词PK助手 - 安装包脚本
;
; 编译：ISCC.exe build\installer.iss
; 产物：release\TianxuePK-Setup-v1.0.0.exe
;
; 踩过的坑（都是实测出来的）：
;   1. 输出文件名与 exe 文件名都用 ASCII。中文名会让安装包静默启动时
;      直接退出（退出码 1 = Setup failed to initialize），连 /LOG 都不生成。
;   2. 不要写 LicenseFile=（空值会干扰初始化）。
;   3. WizardStyle 用 modern dynamic（官方示例写法）。
;   4. 语言文件不在 Inno 默认安装里，要另外下载 ChineseSimplified.isl
;      放到 Inno Setup 6\Languages\ 下。

#define MyAppName "天学网单词PK助手"
#define MyAppVersion "1.0.0"
#define MyAppExeName "TianxuePK.exe"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
WizardStyle=modern dynamic
DefaultDirName={autopf}\TianxuePK
DefaultGroupName={#MyAppName}
Compression=lzma2
SolidCompression=yes
; 输出必须放纯 ASCII 路径：实测安装包放在含中文的目录（如 单词pk）下运行，
; 初始化会失败（退出码 1，不生成 /LOG 日志），换到英文目录就正常。
OutputDir=E:\pk_release
OutputBaseFilename=TianxuePK-Setup-v{#MyAppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequired=lowest

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
Source: "..\dist\TianxuePK\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\data\browser-profile"
