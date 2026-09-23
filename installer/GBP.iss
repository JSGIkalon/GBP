; Instalador de GBP (Inno Setup 6).
;
; No se compila a mano: lo llama tools\build_exe.ps1 despues de PyInstaller,
; pasandole la version con /DAppVersion=... y la carpeta dist\GBP ya armada.
;
; Decisiones:
; - Instalacion **por usuario** (PrivilegesRequired=lowest): no pide
;   administrador. La carpeta por defecto es %LOCALAPPDATA%\Programs\Ikalon\GBP.
; - El asistente es visible entero: bienvenida, condiciones de uso que hay que
;   aceptar, eleccion de carpeta, accesos directos y confirmacion.
; - Los supuestos, la sesion y los ajustes viven en %APPDATA%\Ikalon\GBP y
;   **no** se borran al desinstalar ni al actualizar: son del usuario, no del
;   programa.
; - Los casos son .gbp.json, y Windows asocia por la ultima extension (.json).
;   Asociar todos los .json a GBP seria secuestrar un formato ajeno, asi que
;   GBP solo se registra en «Abrir con», sin cambiar el programa por defecto.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "GBP"
#define AppLongName "GBP - Proyeccion patrimonial"
#define AppExe "GBP.exe"

[Setup]
; El AppId identifica la instalacion entre versiones: no cambiarlo nunca, o
; cada version nueva se instalaria al lado de la anterior en vez de encima.
AppId={{6E4B2C1A-8F3D-4B7E-9A51-2D0C7F4E9B63}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Ikalon Investments
DefaultDirName={autopf}\Ikalon\GBP
DefaultGroupName=Ikalon
PrivilegesRequired=lowest
DisableWelcomePage=no
DisableDirPage=no
DisableProgramGroupPage=yes
DisableReadyPage=no
LicenseFile=licencia.txt
SetupIconFile=..\gbp\data\brand\gbp.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppLongName}
WizardStyle=modern
OutputDir=..\dist
OutputBaseFilename=GBP-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
; Si GBP esta abierto al actualizar, el asistente ofrece cerrarlo.
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\GBP\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Una version nueva no debe arrastrar librerias de la anterior que ya no usa.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "{#AppLongName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; «Abrir con → GBP» para los .json, sin volverlo el programa por defecto.
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppLongName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".json"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\DefaultIcon"; ValueType: string; ValueData: "{app}\{#AppExe},0"
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\.json\OpenWithList\{#AppExe}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir GBP ahora"; Flags: nowait postinstall skipifsilent
