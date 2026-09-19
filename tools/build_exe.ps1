# Empaqueta GBP como .exe portable (un solo archivo, sin instalador).
#
# Uso:  .\tools\build_exe.ps1
# Salida: dist\GBP.exe
#
# Notas:
# - La ruta de --add-data debe ser absoluta; con rutas relativas PyInstaller la
#   resuelve contra el directorio del .spec y no encuentra los datos.
# - Los recursos del LTCMA viajan dentro del .exe y se leen via sys._MEIPASS
#   (ver gbp.model.correlation.data_dir).
# - La libreria de supuestos se escribe en %APPDATA%\Ikalon\GBP, nunca dentro
#   del ejecutable, para que sobreviva a las actualizaciones.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$python = ".\.venv\Scripts\python.exe"
# gbp\data incluye la subcarpeta brand (simbolo, wordmark e icono), asi que
# los recursos de marca viajan dentro del .exe con el mismo --add-data.
$data = (Resolve-Path "gbp\data").Path
$icon = (Resolve-Path "gbp\data\brand\gbp.ico").Path

$started = Get-Date

Write-Host "Cerrando instancias de GBP.exe en ejecucion..."
Get-Process GBP -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500

Write-Host "Limpiando compilaciones anteriores..."
Remove-Item dist, build\GBP, build\GBP.spec -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Empaquetando GBP.exe..."
# PyInstaller escribe su log en stderr; con ErrorActionPreference = Stop eso se
# toma como error fatal aunque el empaquetado vaya bien. Se baja aqui y se
# verifica el resultado por el archivo de salida.
$ErrorActionPreference = "Continue"
& $python -m PyInstaller `
    --onefile `
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
$exe = "dist\GBP.exe"
if (-not (Test-Path $exe)) {
    throw "El empaquetado no produjo $exe"
}
$item = Get-Item $exe
if ($item.LastWriteTime -lt $started) {
    throw ("$exe es de una compilacion anterior ($($item.LastWriteTime)). " +
           "Lo mas probable es que el .exe estuviera en ejecucion y no se pudiera " +
           "sobrescribir: cierralo y vuelve a intentar.")
}

$size = [math]::Round($item.Length / 1MB, 1)
Write-Host ""
Write-Host "Listo: $exe ($size MB)" -ForegroundColor Green
Write-Host "Es portable: copialo donde quieras y ejecutalo, no necesita instalacion."
