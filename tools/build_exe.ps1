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
    --paths . `
    --exclude-module pytest `
    --exclude-module PySide6.QtWebEngineCore `
    --exclude-module PySide6.Qt3DCore `
    --exclude-module PySide6.QtMultimedia `
    --noconfirm `
    run.py

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
