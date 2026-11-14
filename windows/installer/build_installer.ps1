# Construit dist/explorer-draco-step-preview-<version>-setup.exe : Python embarqué, paquets, extension compilée.
# Prérequis : extension déjà compilée (windows/preview/build.ps1, avec OpenCascade pour STEP), Inno Setup 6.
# Le Python embarqué est téléchargé depuis python.org, et sa signature Authenticode vérifiée.
param([string]$PythonVersion = '3.14.8')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot/../..").Path
$build = "$root/windows/preview/build"
$stage = "$root/build/installer/stage"
$cache = "$root/build/installer/cache"
$version = (& "$root/.venv/Scripts/python.exe" -c "import explorer_preview; print(explorer_preview.__version__)").Trim()
foreach ($need in "$build/DracoPreview.dll", "$build/refresh_thumbnails.exe", "$build/step/step_mesh.exe") {
    if (-not (Test-Path $need)) { throw "Manquant : $need (lancer windows/preview/build.ps1 avec OpenCascade)" }
}
if (Test-Path $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
New-Item -ItemType Directory -Force $stage, $cache | Out-Null

# 1. Python embarqué officiel, signature vérifiée.
$zip = "$cache/python-$PythonVersion-embed-amd64.zip"
if (-not (Test-Path $zip)) {
    Invoke-WebRequest "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" -OutFile $zip
}
Expand-Archive $zip "$stage/python"
$signature = Get-AuthenticodeSignature "$stage/python/python.exe"
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
    throw "Signature du Python embarqué invalide : $($signature.Status) $($signature.SignerCertificate.Subject)"
}
$tag = ($PythonVersion -split '\.')[0..1] -join ''
# Chemins du Python embarqué : sa bibliothèque, les paquets, et le dossier de l'application (paquet explorer_preview).
Set-Content -Encoding ascii "$stage/python/python$tag._pth" "python$tag.zip`r`n.`r`nLib\site-packages`r`n..`r`n"

# 2. Paquets binaires pour cette version de Python (PySide6 Essentials seulement : Qt sans les modules lourds).
& "$root/.venv/Scripts/python.exe" -m pip install --quiet --no-compile --only-binary :all: --platform win_amd64 `
    --python-version $PythonVersion --implementation cp --target "$stage/python/Lib/site-packages" `
    numpy==2.5.4 DracoPy==2.2.0 PySide6_Essentials==6.12.0 shiboken6==6.12.0
if ($LASTEXITCODE) { throw 'pip failed' }
$qt = "$stage/python/Lib/site-packages/PySide6"
# Modules Qt inutiles à l'aperçu (Qml, Quick, Pdf, Designer, outils) : environ deux tiers du poids de PySide6.
Get-ChildItem $qt -File | Where-Object { $_.Name -match '^(Qt6(Qml|Quick|Pdf|Designer|Help|UiTools|Svg|Sql|Test|Concurrent|Xml|DBus|Network|PrintSupport|StateMachine|LabsAnimation)|Qt(Qml|Quick|Pdf|Designer|Help|UiTools|Svg|Sql|Test|Concurrent|Xml|DBus|Network|PrintSupport|StateMachine))' -or $_.Extension -eq '.exe' } | Remove-Item -Force
foreach ($dir in 'qml', 'translations', 'include', 'typesystems', 'glue', 'scripts', 'metatypes', 'resources') {
    if (Test-Path "$qt/$dir") { Remove-Item -LiteralPath "$qt/$dir" -Recurse -Force }
}

# 3. L'extension, dans la même disposition que le dépôt (le lecteur STEP est cherché en windows/preview/build/step).
Copy-Item -Recurse "$root/explorer_preview" "$stage/explorer_preview"
Get-ChildItem "$stage/explorer_preview" -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
New-Item -ItemType Directory -Force "$stage/windows/preview/build" | Out-Null
Copy-Item "$root/windows/preview/register.py", "$PSScriptRoot/configure_installed.py" "$stage/windows/preview/"
Copy-Item "$build/DracoPreview.dll", "$build/refresh_thumbnails.exe" "$stage/windows/preview/build/"
Copy-Item -Recurse "$build/step" "$stage/windows/preview/build/step"
Get-ChildItem "$stage/windows/preview/build/step" -File | Where-Object { $_.Extension -in '.lib', '.exp', '.obj' } | Remove-Item -Force
Copy-Item "$root/LICENSE", "$root/THIRD-PARTY-NOTICES.md", "$root/README.md" $stage

# 4. Contrôle : le Python embarqué charge l'aperçu et dessine une miniature hors fenêtre.
$probe = "$cache/probe.drc"
& "$root/.venv/Scripts/python.exe" -c "import DracoPy, numpy as np, sys; open(sys.argv[1],'wb').write(DracoPy.encode(np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1]],float), np.array([[0,1,2],[0,2,3],[0,3,1],[1,3,2]],np.uint32)))" $probe
& "$stage/python/python.exe" -I "$stage/explorer_preview/shell_preview.py" --input $probe --output "$cache/probe.png" --size 64
if ($LASTEXITCODE -or -not (Test-Path "$cache/probe.png")) { throw 'Le Python embarqué ne dessine pas la miniature' }

$iscc = @("$env:LOCALAPPDATA/Programs/Inno Setup 6/ISCC.exe", "${env:ProgramFiles(x86)}/Inno Setup 6/ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 introuvable (winget install JRSoftware.InnoSetup --scope user)' }
& $iscc /Qp "/DAppVersion=$version" "/DStage=$stage" "/DOutDir=$root/dist" "$PSScriptRoot/explorer-preview.iss"
if ($LASTEXITCODE) { throw 'Inno Setup failed' }
Get-Item "$root/dist/explorer-draco-step-preview-$version-setup.exe"
