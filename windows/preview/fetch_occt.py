"""Télécharge OpenCascade 8.0.1 et les DLL dont il dépend (paquets conda-forge win-64 épinglés) dans third_party.

Chaque archive est vérifiée par son SHA-256 publié sur anaconda.org avant extraction.
OpenCascade : Library/bin, include et lib. Dépendances : seulement les DLL de Library/bin.
Usage : python -I windows/preview/fetch_occt.py
"""
from pathlib import Path
import hashlib
import io
import json
import tarfile
import urllib.request
import zipfile
from compression import zstd

ROOT = Path(__file__).resolve().parents[2] / 'third_party'
OCCT = 'win-64/occt-8.0.1-novtk_h6bfc850_101.conda'
DEPENDENCIES = [
    'win-64/freeimage-3.18.0-h17567e8_27.conda',
    'win-64/libfreetype6-2.14.3-hdbac1cb_2.conda',
    'win-64/imath-3.2.3-h1608b31_1.conda',
    'win-64/libjpeg-turbo-3.2.1-hfd05255_0.conda',
    'win-64/libpng-1.6.59-hdc8cecf_0.conda',
    'win-64/libraw-0.22.3-h345c428_0.conda',
    'win-64/libtiff-4.7.2-hef6d50c_2.conda',
    'win-64/libwebp-base-1.6.0-h4d5522a_1.conda',
    'win-64/libzlib-1.3.2-hfd05255_3.conda',
    'win-64/openexr-3.5.4-h4a61e80_0.conda',
    'win-64/openjpeg-2.5.4-h90fa87c_2.conda',
    'win-64/lerc-4.3.0-hd936e49_0.conda',
    'win-64/libdeflate-1.26-h1a1d4e4_0.conda',
    'win-64/zstd-1.5.7-h534d264_7.conda',
    'win-64/liblzma-5.8.3-hfd05255_1.conda',
    'win-64/lcms2-2.20-hf2c6c5f_0.conda',
    'win-64/openjph-0.33.0-hf13a347_0.conda',
]


def package_name(basename):
    return basename.split('/')[-1].rsplit('-', 2)[0]


def fetch(basename):
    with urllib.request.urlopen(f'https://api.anaconda.org/package/conda-forge/{package_name(basename)}/files') as r:
        record = next(f for f in json.load(r) if f['basename'] == basename)
    expected = record.get('sha256') or record['attrs'].get('sha256')
    if not expected:
        raise RuntimeError(f'{basename}: no published SHA-256')
    with urllib.request.urlopen('https://conda.anaconda.org/conda-forge/' + basename) as r:
        data = r.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError(f'{basename}: SHA-256 mismatch')
    archive = zipfile.ZipFile(io.BytesIO(data))
    inner = next(n for n in archive.namelist() if n.startswith('pkg-'))
    return tarfile.open(fileobj=io.BytesIO(zstd.decompress(archive.read(inner))))


def main():
    tar = fetch(OCCT)
    members = [m for m in tar.getmembers() if m.name.startswith(('Library/bin/', 'Library/include/', 'Library/lib/'))]
    tar.extractall(ROOT / 'occt-8.0.1', members=members, filter='data')
    print('occt 8.0.1', len(members), 'fichiers')
    for basename in DEPENDENCIES:
        tar = fetch(basename)
        members = [m for m in tar.getmembers() if m.name.startswith('Library/bin/') and m.name.lower().endswith('.dll')]
        tar.extractall(ROOT / 'occt-deps' / package_name(basename), members=members, filter='data')
        print(package_name(basename), [m.name.split('/')[-1] for m in members])


if __name__ == '__main__':
    main()
