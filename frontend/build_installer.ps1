$ErrorActionPreference = "Stop"

$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
$iss = Join-Path $PSScriptRoot "JuntaCRM-Frontend.iss"
$spec = Join-Path $PSScriptRoot "JuntaCRM-Frontend.spec"

if (!(Test-Path $iscc)) {
    throw "ISCC.exe nao encontrado em '$iscc'. Instale o Inno Setup 6."
}

if (!(Test-Path $iss)) {
    throw "Arquivo .iss nao encontrado: $iss"
}

if (!(Test-Path $spec)) {
    throw "Arquivo .spec nao encontrado: $spec"
}

# Sempre recria o exe com os arquivos de dados corretos (ex.: flet icons.json).
& python -m PyInstaller --noconfirm --clean $spec
if ($LASTEXITCODE -ne 0) {
    throw "Falha ao gerar executavel com PyInstaller (exit code $LASTEXITCODE)."
}

& $iscc $iss
if ($LASTEXITCODE -ne 0) {
    throw "Falha ao compilar installer com Inno Setup (exit code $LASTEXITCODE)."
}

Write-Host "Installer gerado em: $PSScriptRoot\installer_output" -ForegroundColor Green
