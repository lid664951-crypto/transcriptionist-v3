; 音译家 AI音效管理工具1.1.0 - Inno Setup 安装脚本
; 使用前请先运行 build.bat 完成 PyInstaller 打包，再运行本脚本或由 build.bat 自动调用
; 安装包使用项目图标 ui/resources/icons/app_icon.ico

#define MyAppName "音译家 AI音效管理工具1.1.0"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "音译家"
#define MyAppURL "https://github.com/quodlibet/transcriptionist"
#define MyAppExeName "音译家 AI音效管理工具1.1.0.exe"
#define PyInstallerOutput "dist\音译家 AI音效管理工具1.1.0"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; 安装包输出路径与文件名（与绿色版主程序同名，带版本：音译家 AI音效管理工具1.1.0）
OutputDir=dist
OutputBaseFilename=音译家 AI音效管理工具1.1.0
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; 需要管理员权限（写入 Program Files）
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
; 架构
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 安装包使用项目图标（build.bat 会先运行 convert_icon.py 生成 app_icon.ico）
SetupIconFile=ui\resources\icons\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

; 仅用英文向导（Default.isl 所有 Inno 安装都有）；应用名、安装目录等仍为中文
; 若需中文向导，请确保 Inno 安装目录 Languages\ChineseSimplified.isl 存在后再加回 chinesesimplified
[Languages]
; 中文向导语言文件在某些 Inno 安装里可能缺失（会导致编译失败）。
; 解决：把中文语言文件放到项目里即可（不依赖 Inno 安装路径）：
;   packaging\installer_lang\ChineseSimplified.isl
; 下载来源（官方翻译页给出的 raw 链接）：
;   https://raw.githubusercontent.com/jrsoftware/issrc/refs/heads/main/Files/Languages/Unofficial/ChineseSimplified.isl
#ifexist "packaging\\installer_lang\\ChineseSimplified.isl"
Name: "chinesesimplified"; MessagesFile: "packaging\\installer_lang\\ChineseSimplified.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1; Check: not IsAdminInstallMode

[Files]
; 将 PyInstaller 输出的整个目录打包进安装程序
Source: "{#PyInstallerOutput}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时清理运行时生成的数据（日志、数据库、缓存等）
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\config"
; 清理可能生成的 Python 缓存
Type: filesandordirs; Name: "{app}\runtime\python\__pycache__"
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
; 最后尝试删除安装目录（如果为空）
Type: dirifempty; Name: "{app}"
