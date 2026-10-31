; 天学网单词PK助手 - 安装包脚本
;
; 编译：ISCC.exe build\installer.iss
; 产物：release\TianxuePK-Setup-v1.1.0.exe
;
; 注意事项：
;   1. 输出文件名与 exe 文件名都用 ASCII。中文名会让安装包静默启动时
;      直接退出（退出码 1 = Setup failed to initialize），连 /LOG 都不生成。
;   2. 不要写 LicenseFile=（空值会干扰初始化）。
;   3. WizardStyle 用 modern dynamic（官方示例写法）。
;   4. 语言文件不在 Inno 默认安装里，要另外下载 ChineseSimplified.isl
;      放到 Inno Setup 6\Languages\ 下。
;   5. 不要让用户把程序装到含中文的目录：Inno 卸载器在该路径下会报
;      「无法创建目录 ... 错误 5」，默认目录 %LOCALAPPDATA%\Programs\TianxuePK 不受影响。

#define MyAppName "天学网单词PK助手"
#define MyAppVersion "1.1.0"
#define MyAppExeName "TianxuePK.exe"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
WizardStyle=modern dynamic
DefaultDirName={autopf}\TianxuePK
DefaultGroupName={#MyAppName}
Compression=lzma2
SolidCompression=yes
; 输出目录必须是纯 ASCII 路径：放在含中文的目录下初始化会失败
; （退出码 1，不生成 /LOG），换到英文目录即可。
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
; config.toml 单独处理：已存在就不覆盖，卸载时保留（用户的开关和设置不丢）
Source: "..\dist\TianxuePK\*"; DestDir: "{app}"; Excludes: "config.toml"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\TianxuePK\config.toml"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\data\browser-profile"
