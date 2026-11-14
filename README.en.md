# explorer-draco-step-preview

*[Version française](README.md)*

Thumbnails and 3D preview of **Draco** (`.drc`), **STEP** (`.step`, `.stp`), **STL**, **OBJ** and **3MF** files right in Windows File Explorer: folder icons and the preview pane (Alt+P), where the model can be rotated with the mouse.

- **Draco**: every face is drawn with OpenGL, Z up as in a slicer.
- **STEP**: read with OpenCascade, with part and face colours; glazing (polycarbonate, glass…) is see-through. Tested up to a 142 MB assembly (Rat Rig V-Core 4.1, 790 parts).
- **STL, OBJ, 3MF**: face colours (VisCAM and Magics binary STL), vertex colours (OBJ) and material colours (3MF); text or binary STL, even truncated; multi-part 3MF projects. Takes over PowerToys STL thumbnails and the Windows 3MF handler, restored on uninstall.
- **Isolated**: each preview runs in a separate low-integrity process with memory and time limits. A malicious or oversized file cannot hang Explorer.
- **Reversible**: per-user install, no administrator rights. The default app is never changed, and uninstalling restores the registry exactly.

Started alongside [dracoconv](https://github.com/DrFreeman001/dracoconv), the Draco converter for 3D-printing model collections.

## Installation

**Easiest:** download `explorer-draco-step-preview-<version>-setup.exe` from the [releases](https://github.com/DrFreeman001/explorer-draco-step-preview/releases/latest) and run it (about 56 MB, nothing else to install: Python and OpenCascade are included). Per-user install, no administrator rights; uninstall from "Installed apps", which restores the registry. The installer is not signed, so Windows SmartScreen may say "unknown publisher": "More info", then "Run anyway".

**From source:** Windows 10 or 11 x64, Python 3.11 or newer, Microsoft C++ build tools (Visual Studio Build Tools, "Desktop development with C++" workload). From PowerShell:

```powershell
git clone https://github.com/DrFreeman001/explorer-draco-step-preview.git
cd explorer-draco-step-preview
py -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python windows\preview\configure.py
python -I windows\preview\fetch_occt.py     # once, for STEP: OpenCascade (about 140 MB) into third_party
.\windows\preview\build.ps1
.venv\Scripts\python windows\preview\register.py install
```

Then restart Explorer, or sign out. Without `fetch_occt.py`, only `.drc` files are handled.

Uninstall:

```powershell
.venv\Scripts\python windows\preview\register.py uninstall
```

To build the installer (Inno Setup 6 required): `.\windows\installer\build_installer.ps1`.

Keep the folder in place while the extension is installed: the registry points to it, and `windows\preview\build\registration.json` is used for an exact uninstall.

## Limits

- At most 64 MB for a Draco file, 200 MB for a STEP, STL, OBJ or 3MF file; 90 s and 3 GB of memory per preview.
- One open preview at a time; a second window says so.
- The keyboard works only after clicking in the model (R resets the view).
- Large STEP files are slow: about 50 s for 142 MB. The mesh is kept for at most one hour so the thumbnail and the preview do not read it twice.
- If Microsoft "3D Viewer" is installed, it keeps the preview pane for STL, OBJ and 3MF: a Store app wins over registry settings. Thumbnails stay ours. To get the preview too, uninstall 3D Viewer (no longer developed by Microsoft) from "Installed apps".
- Cached thumbnails are not redrawn: Windows keeps them until the file changes or the cache is cleared (Disk Cleanup → Thumbnails).

Technical notes (French): [windows/preview/README.md](windows/preview/README.md). Measurements: [windows/preview/verification.md](windows/preview/verification.md).

## License

Apache-2.0. Third-party components: [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
