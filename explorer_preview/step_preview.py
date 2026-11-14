"""Lecture des fichiers STEP pour l'aperçu : step_mesh.exe (OpenCascade natif) découpe en triangles.

L'outil natif tourne dans son propre processus, enfant de l'auxiliaire d'aperçu et donc dans le même
job Windows. Il écrit un maillage compact que l'on relit et vérifie ici.
"""
from __future__ import annotations
from pathlib import Path
import hashlib
import os
import re
import subprocess
import time
import numpy as np
from explorer_preview.preview_rendering import MAX_FACES, MAX_VERTICES, DisplayMesh, prepare_arrays

STEP_TOOL = Path(__file__).resolve().parents[1] / 'windows' / 'preview' / 'build' / 'step' / 'step_mesh.exe'
MAGIC = b'DCMESH3\0'
# L’auxiliaire dispose de 90 s en tout (bridge.cpp) ; on garde de quoi démarrer Qt et dessiner.
TIMEOUT = 80
# Un assemblage STEP complet dépasse vite 100 Mo (Rat Rig V-Core 4.1 : 142 Mo, lu en 47 s avec 1,6 Gio).
MAX_INPUT = 200 * 1024 * 1024
_ERRORS = {2: 'Invalid STEP input', 3: 'STEP file has no surfaces', 4: 'STEP model exceeds preview limit',
           5: 'Cannot write STEP mesh', 6: 'STEP reader failed'}


# Explorer demande la miniature et l'aperçu séparément : sans cache, un gros assemblage est lu deux fois de suite.
# Le maillage d'une lecture longue est donc gardé un court moment, sous l'empreinte du contenu du fichier.
CACHE_MIN_SECONDS = 5
CACHE_SECONDS = 3600
CACHE_ENTRIES = 2
_CACHED = re.compile(r'[0-9a-f]{64}\.mesh')


def _cache_dir(output: Path) -> Path | None:
    """Dossier du cache, seulement quand output est dans un dossier temporaire de l'aperçu."""
    base = output.parent.parent
    return base / 'mesh-cache' if base.name == 'DracoConvPreview' else None


def _digest(source: Path) -> str:
    digest = hashlib.sha256()
    with open(source, 'rb') as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def prune_cache(cache: Path, now: float | None = None) -> None:
    """Retire les maillages de plus de CACHE_SECONDS et ne garde que les CACHE_ENTRIES plus récents."""
    now = time.time() if now is None else now
    try:
        entries = [p for p in cache.iterdir() if _CACHED.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
    except OSError:
        return
    entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for rank, entry in enumerate(entries):
        if rank >= CACHE_ENTRIES or now - entry.stat().st_mtime > CACHE_SECONDS:
            try:
                entry.unlink()
            except OSError:
                pass


def is_step(head: bytes) -> bool:
    return head.lstrip(b'\xef\xbb\xbf').lstrip(b' \t\r\n').startswith(b'ISO-10303-21')


def read_mesh_file(path: Path) -> DisplayMesh:
    data = Path(path).read_bytes()
    if len(data) < 16 or data[:8] != MAGIC:
        raise ValueError('Invalid STEP mesh')
    vertices, faces = (int(n) for n in np.frombuffer(data, '<u4', 2, 8))
    if not 0 < vertices <= MAX_VERTICES or not 0 < faces <= MAX_FACES:
        raise ValueError('Invalid STEP mesh counts')
    if len(data) != 16 + 16 * vertices + 12 * faces:
        raise ValueError('Truncated STEP mesh')
    points = np.frombuffer(data, '<f4', vertices * 3, 16).reshape(-1, 3)
    indices = np.frombuffer(data, '<u4', faces * 3, 16 + 12 * vertices).reshape(-1, 3)
    mesh = prepare_arrays(points, indices)
    # Couleur sRGB et opacité de chaque sommet, lues dans le fichier STEP (bleu opaque pour les faces sans couleur).
    mesh.colors = np.frombuffer(data, np.uint8, vertices * 4, 16 + 12 * vertices + 12 * faces).reshape(-1, 4).copy()
    # Les faces translucides passent en dernier : elles se dessinent par-dessus les faces opaques.
    translucent = mesh.colors[mesh.faces[:, 0], 3] < 255
    if translucent.any():
        mesh.faces = np.ascontiguousarray(mesh.faces[np.argsort(translucent, kind='stable')])
        mesh.opaque_faces = int(len(translucent) - translucent.sum())
    return mesh


def mesh_step(source: Path, output: Path, tool: Path = STEP_TOOL, timeout: float = TIMEOUT) -> DisplayMesh:
    """Découpe source en triangles ; le fichier intermédiaire output est supprimé après lecture."""
    tool, output = Path(tool), Path(output)
    if not tool.exists():
        raise ValueError('STEP reader is not installed')
    cache, entry = _cache_dir(output), None
    if cache is not None:
        prune_cache(cache)
        entry = cache / (_digest(source) + '.mesh')
        if entry.is_file() and not entry.is_symlink():
            try:
                return read_mesh_file(entry)
            except (OSError, ValueError):
                entry.unlink(missing_ok=True)
    started = time.monotonic()
    try:
        result = subprocess.run([str(tool), str(source), str(output)], capture_output=True, timeout=timeout,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise ValueError(_ERRORS.get(result.returncode, f'STEP reader failed ({result.returncode})'))
        mesh = read_mesh_file(output)
        if entry is not None and time.monotonic() - started >= CACHE_MIN_SECONDS:
            try:
                cache.mkdir(exist_ok=True)
                os.replace(output, entry)
            except OSError:
                pass
        return mesh
    except subprocess.TimeoutExpired as exc:
        raise ValueError('STEP reading took too long') from exc
    finally:
        for leftover in (output, output.with_name(output.name + '.part')):
            leftover.unlink(missing_ok=True)
