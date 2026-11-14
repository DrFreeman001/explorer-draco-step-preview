# Compile l'extension Explorateur : DLL, sondes de contrôle et lecteur STEP.
# -StepOnly  : ne recompile que le lecteur STEP (la DLL est verrouillée tant qu'Explorer l'a chargée).
# -CheckOnly : compile bridge.cpp sans édition de liens, pour vérifier le code sans toucher à la DLL installée.
param([switch]$StepOnly, [switch]$CheckOnly)
$ErrorActionPreference='Stop'

# Outils Microsoft C++ et SDK Windows : les plus récents installés, trouvés par vswhere et le registre.
$vswhere="${env:ProgramFiles(x86)}/Microsoft Visual Studio/Installer/vswhere.exe"
if(-not (Test-Path $vswhere)){throw 'Outils de compilation Microsoft C++ introuvables (vswhere.exe absent)'}
$install=& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if(-not $install){throw 'Aucune installation de Visual Studio avec les outils C++ x64'}
$vc=(Get-ChildItem "$install/VC/Tools/MSVC" -Directory | Sort-Object {[version]$_.Name} -Descending | Select-Object -First 1).FullName
$sdk=(Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows Kits\Installed Roots').KitsRoot10.TrimEnd('\')
$version=(Get-ChildItem "$sdk/Include" -Directory | Where-Object {Test-Path "$($_.FullName)/um/windows.h"} | Sort-Object {[version]$_.Name} -Descending | Select-Object -First 1).Name
if(-not $vc -or -not $version){throw 'Compilateur ou SDK Windows introuvable'}
$cl="$vc/bin/Hostx64/x64/cl.exe"
$env:INCLUDE="$vc/include;$sdk/Include/$version/ucrt;$sdk/Include/$version/um;$sdk/Include/$version/shared"
$env:LIB="$vc/lib/x64;$sdk/Lib/$version/ucrt/x64;$sdk/Lib/$version/um/x64"
$build="$PSScriptRoot/build"
New-Item -ItemType Directory -Force $build | Out-Null

if($CheckOnly){
 & $cl /nologo /utf-8 /EHsc /std:c++17 /W4 /DUNICODE /D_UNICODE /c "$PSScriptRoot/bridge.cpp" /Fo"$build/bridge-check.obj"
 if($LASTEXITCODE){throw 'Bridge compile failed'}
 Remove-Item "$build/bridge-check.obj"
 return
}

if(-not $StepOnly){
 & $cl /nologo /utf-8 /EHsc /std:c++17 /W4 /DUNICODE /D_UNICODE "$PSScriptRoot/probes/probe.cpp" /Fo"$build/probe.obj" /Fe"$build/probe.exe" /link ole32.lib shlwapi.lib gdi32.lib uuid.lib
 if($LASTEXITCODE){throw 'Probe compile failed'}
 & $cl /nologo /utf-8 /EHsc /std:c++17 /W4 /DUNICODE /D_UNICODE /LD "$PSScriptRoot/bridge.cpp" /Fo"$build/bridge.obj" /Fe"$build/DracoPreview.dll" /link /DEF:"$PSScriptRoot/bridge.def" ole32.lib shell32.lib shlwapi.lib gdi32.lib user32.lib uuid.lib windowscodecs.lib advapi32.lib
 if($LASTEXITCODE){throw 'Bridge compile failed'}
 foreach($name in @('preview_probe','cache_probe')) {
  & $cl /nologo /utf-8 /EHsc /std:c++17 "$PSScriptRoot/probes/$name.cpp" /Fo"$build/$name.obj" /Fe"$build/$name.exe" /link ole32.lib shell32.lib shlwapi.lib user32.lib uuid.lib
  if($LASTEXITCODE){throw "$name compile failed"}
 }
}

# Lecteur STEP : OpenCascade 8.0.1 (paquet conda-forge « novtk ») et ses DLL dans third_party, voir README.
$occt="$PSScriptRoot/../../third_party/occt-8.0.1/Library"
if(Test-Path "$occt/include/opencascade"){
 New-Item -ItemType Directory -Force "$build/step" | Out-Null
 $env:INCLUDE="$env:INCLUDE;$occt/include/opencascade"
 $env:LIB="$env:LIB;$occt/lib"
 & $cl /nologo /utf-8 /EHsc /std:c++17 /O2 /MD /W3 /DUNICODE /D_UNICODE /DWNT "$PSScriptRoot/step_mesh.cpp" /Fo"$build/step_mesh.obj" /Fe"$build/step/step_mesh.exe" /link TKernel.lib TKMath.lib TKBRep.lib TKG2d.lib TKG3d.lib TKGeomBase.lib TKTopAlgo.lib TKMesh.lib TKDESTEP.lib TKXSBase.lib TKDE.lib TKXCAF.lib TKLCAF.lib TKCDF.lib
 if($LASTEXITCODE){throw 'step_mesh compile failed'}
 & "$PSScriptRoot/../../.venv/Scripts/python.exe" -I "$PSScriptRoot/stage_step.py" "$vc/bin/Hostx64/x64/dumpbin.exe"
 if($LASTEXITCODE){throw 'step_mesh staging failed'}
}
