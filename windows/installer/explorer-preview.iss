; Installateur de l'extension Explorateur : pour l'utilisateur courant, sans droits d'administrateur.
; Construit par windows/installer/build_installer.ps1, qui prépare le dossier Stage.

#define AppName "explorer-draco-step-preview"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{9C3E5A71-4B2D-4F86-A0E3-6D1B7C2F8E95}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName=Explorer Draco STEP preview {#AppVersion}
AppPublisher=DrFreeman001
AppPublisherURL=https://github.com/DrFreeman001/explorer-draco-step-preview
AppSupportURL=https://github.com/DrFreeman001/explorer-draco-step-preview/issues
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile={#Stage}\LICENSE
OutputDir={#OutDir}
OutputBaseFilename={#AppName}-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; La DLL est chargée par l'Explorateur : pas de fermeture d'applications, remplacement au redémarrage si besoin.
CloseApplications=no
RestartIfNeededByRun=no
UninstallDisplayName=Explorer Draco STEP preview {#AppVersion}

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
fr.Registering=Inscription de l'extension dans l'Explorateur…
en.Registering=Registering the Explorer extension…
fr.Finished=Les miniatures et l'aperçu (Alt+P) apparaissent dans les nouvelles fenêtres de l'Explorateur ; fermez votre session ou redémarrez l'Explorateur pour les avoir partout.
en.Finished=Thumbnails and the preview (Alt+P) appear in new Explorer windows; sign out or restart Explorer to get them everywhere.

[Messages]
fr.FinishedLabel=[name] est installé.%n%n{cm:Finished}
en.FinishedLabel=[name] is installed.%n%n{cm:Finished}

[Files]
Source: "{#Stage}\windows\preview\build\DracoPreview.dll"; DestDir: "{app}\windows\preview\build"; Flags: ignoreversion restartreplace uninsrestartdelete
Source: "{#Stage}\*"; Excludes: "DracoPreview.dll"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Run]
Filename: "{app}\python\python.exe"; Parameters: "-I ""{app}\windows\preview\configure_installed.py"""; StatusMsg: "{cm:Registering}"; Flags: runhidden
Filename: "{app}\python\python.exe"; Parameters: "-I ""{app}\windows\preview\register.py"" uninstall"; Flags: runhidden
Filename: "{app}\python\python.exe"; Parameters: "-I ""{app}\windows\preview\register.py"" install"; StatusMsg: "{cm:Registering}"; Flags: runhidden

[UninstallRun]
Filename: "{app}\python\python.exe"; Parameters: "-I ""{app}\windows\preview\register.py"" uninstall"; RunOnceId: "Unregister"; Flags: runhidden

[UninstallDelete]
Type: files; Name: "{app}\windows\preview\build\preview.ini"
Type: files; Name: "{app}\windows\preview\build\registration.json"
Type: filesandordirs; Name: "{app}\explorer_preview\__pycache__"
Type: filesandordirs; Name: "{app}\python\Lib\site-packages\__pycache__"
Type: dirifempty; Name: "{app}"
