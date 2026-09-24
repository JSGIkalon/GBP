# Empaqueta GBP y arma su instalador.
#
# Uso:  .\tools\build_exe.ps1
# Salida: dist\GBP\GBP.exe            (la app en carpeta, lo que se instala)
#         dist\GBP-Setup-<version>.exe (el instalador, lo que se entrega)
#
# Notas:
# - PyInstaller en modo carpeta (--onedir), no un solo archivo: el .exe de un
#   solo archivo se descomprime entero a %TEMP% en cada arranque, y eso eran
#   varios segundos de espera y el patron que mas falsos positivos da en los
#   antivirus. Instalada, la carpeta ya esta descomprimida.
# - La ruta de --add-data debe ser absoluta; con rutas relativas PyInstaller la
#   resuelve contra el directorio del .spec y no encuentra los datos.
# - Los recursos del LTCMA viajan dentro de la carpeta y se leen via
#   sys._MEIPASS (ver gbp.model.correlation.data_dir).
# - La libreria de supuestos se escribe en %APPDATA%\Ikalon\GBP, nunca dentro
#   de la carpeta de instalacion, para que sobreviva a las actualizaciones.
# - El instalador lo compila Inno Setup 6 desde installer\GBP.iss. La version
#   sale de gbp\__init__.py.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$python = ".\.venv\Scripts\python.exe"
# gbp\data incluye la subcarpeta brand (simbolo, wordmark e icono), asi que
# los recursos de marca viajan con el mismo --add-data.
$data = (Resolve-Path "gbp\data").Path
$icon = (Resolve-Path "gbp\data\brand\gbp.ico").Path

$version = (Select-String -Path "gbp\__init__.py" -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
if (-not $version) { throw "No se encontro __version__ en gbp\__init__.py" }

# Inno Setup puede estar instalado por usuario o para toda la maquina.
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    throw "No se encontro Inno Setup 6. Instalalo con: winget install JRSoftware.InnoSetup"
}

$started = Get-Date

Write-Host "Cerrando instancias de GBP.exe en ejecucion..."
# Primero se pide cerrar la ventana, que dispara closeEvent y guarda la sesion
# del usuario. Matar el proceso de entrada se saltaba ese guardado.
$abiertos = Get-Process GBP -ErrorAction SilentlyContinue
foreach ($p in $abiertos) { [void]$p.CloseMainWindow() }
foreach ($p in $abiertos) { [void]$p.WaitForExit(5000) }
Get-Process GBP -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500

Write-Host "Limpiando compilaciones anteriores..."
Remove-Item dist, build\GBP, build\GBP.spec -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Empaquetando GBP $version..."
# PyInstaller e ISCC escriben su log en stderr; con ErrorActionPreference = Stop
# eso se toma como error fatal aunque el empaquetado vaya bien. Se baja aqui y
# se verifica el resultado por los archivos de salida.
$ErrorActionPreference = "Continue"
& $python -m PyInstaller `
    --onedir `
    --windowed `
    --name GBP `
    --icon "$icon" `
    --add-data "$data;gbp/data" `
    --paths "$((Get-Location).Path)" `
    --specpath build `
    --exclude-module pytest `
    --exclude-module pandas `
    --exclude-module PySide6.QtWebEngineCore `
    --exclude-module PySide6.Qt3DCore `
    --exclude-module PySide6.QtMultimedia `
    --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.QtQml `
    --exclude-module PySide6.QtNetwork `
    --exclude-module PySide6.QtPdf `
    --exclude-module PySide6.QtOpenGL `
    --exclude-module PySide6.QtVirtualKeyboard `
    --exclude-module PIL.AvifImagePlugin `
    --noconfirm `
    run.py

# Lo que PyInstaller arrastra por los plugins de Qt aunque la app no lo use:
# render OpenGL por software (casi 20 MB), QML/Quick, el visor de PDF de Qt,
# red y TLS, y el teclado virtual. La app es solo widgets y matplotlib: el PDF
# lo escribe matplotlib, no Qt. Si algo de esto resultara necesario, el smoke
# test del final lo detecta antes de armar el instalador.
$internal = "dist\GBP\_internal"
$sobrantes = @(
    "PySide6\opengl32sw.dll",
    "PySide6\Qt6Quick.dll", "PySide6\Qt6Qml.dll", "PySide6\Qt6QmlModels.dll",
    "PySide6\Qt6QmlMeta.dll", "PySide6\Qt6QmlWorkerScript.dll",
    "PySide6\Qt6Pdf.dll", "PySide6\Qt6OpenGL.dll", "PySide6\Qt6VirtualKeyboard.dll",
    "PySide6\Qt6Network.dll", "PySide6\QtNetwork.pyd",
    "PySide6\plugins\imageformats\qpdf.dll",
    "PySide6\plugins\platforminputcontexts",
    "PySide6\plugins\networkinformation",
    "PySide6\plugins\tls",
    "libcrypto-3.dll", "libssl-3.dll",
    "PIL\_avif.cp312-win_amd64.pyd"
)
foreach ($s in $sobrantes) {
    $p = Join-Path $internal $s
    if (Test-Path $p) { Remove-Item $p -Recurse -Force }
}
# Traducciones de Qt: la interfaz está en español con textos propios.
Get-ChildItem "$internal\PySide6\translations" -Filter *.qm -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notlike "qtbase_es*" } | Remove-Item -Force

# No basta con que el archivo exista: si una copia del .exe sigue corriendo,
# PyInstaller falla al sobrescribirlo y queda el ejecutable ANTERIOR en su
# sitio. Ya paso una vez y el script dijo "Listo" sobre el archivo viejo.
function Assert-Fresh($path) {
    if (-not (Test-Path $path)) { throw "El empaquetado no produjo $path" }
    $item = Get-Item $path
    if ($item.LastWriteTime -lt $started) {
        throw ("$path es de una compilacion anterior ($($item.LastWriteTime)). " +
               "Lo mas probable es que estuviera en uso y no se pudiera " +
               "sobrescribir: cierralo y vuelve a intentar.")
    }
    return $item
}

Assert-Fresh "dist\GBP\GBP.exe" | Out-Null

Write-Host "Probando el ejecutable (ventana, simulacion y PDF)..."
# Con datos propios en una carpeta temporal: no toca la sesion del usuario.
$smoke = Join-Path $env:TEMP "gbp_build_smoke"
Remove-Item $smoke -Recurse -Force -ErrorAction SilentlyContinue
$proc = Start-Process "dist\GBP\GBP.exe" -ArgumentList "--smoke-test", "`"$smoke`"" -PassThru -Wait
$log = Join-Path $smoke "smoke.log"
if ($proc.ExitCode -ne 0 -or -not (Test-Path $log) -or (Get-Content $log -TotalCount 1) -ne "ok") {
    if (Test-Path $log) { Get-Content $log | Write-Host }
    throw "El ejecutable empaquetado no paso el smoke test (codigo $($proc.ExitCode))."
}
Write-Host "  $((Get-Content $log) -join ' | ')"

Write-Host "Compilando el instalador..."
& $iscc /Q "/DAppVersion=$version" "installer\GBP.iss"

$setup = Assert-Fresh "dist\GBP-Setup-$version.exe"
$appSize = [math]::Round(((Get-ChildItem "dist\GBP" -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)
$setupSize = [math]::Round($setup.Length / 1MB, 1)

Write-Host ""
Write-Host "Listo:" -ForegroundColor Green
Write-Host "  App instalada   : dist\GBP\ ($appSize MB)"
Write-Host "  Instalador      : $($setup.FullName) ($setupSize MB)" -ForegroundColor Green
Write-Host "Entrega el instalador: se instala por usuario, sin pedir administrador."
