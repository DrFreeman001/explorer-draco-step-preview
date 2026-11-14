"""Copie à côté de step_mesh.exe les DLL dont il a besoin, trouvées dans third_party.

Parcourt les dépendances avec dumpbin ; les DLL du système et du runtime Visual C++ restent celles de Windows.
Usage : python -I windows/preview/stage_step.py <dumpbin.exe>
"""
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TARGET = HERE / 'build' / 'step'
SOURCES = [ROOT / 'third_party' / 'occt-8.0.1' / 'Library' / 'bin',
           *sorted((ROOT / 'third_party' / 'occt-deps').glob('*/Library/bin'))]


def dependents(dumpbin, path):
    out = subprocess.run([dumpbin, '/nologo', '/dependents', str(path)], capture_output=True, text=True, check=True).stdout
    return [line.strip() for line in out.splitlines() if line.startswith('    ') and line.strip().lower().endswith('.dll')]


def find(name):
    for folder in SOURCES:
        candidate = folder / name
        if candidate.exists():
            return candidate
    return None


def main():
    dumpbin = sys.argv[1]
    seen, todo, system = set(), [TARGET / 'step_mesh.exe'], set()
    while todo:
        for name in dependents(dumpbin, todo.pop()):
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            source = find(name)
            if source is None:
                system.add(name)
                continue
            shutil.copy2(source, TARGET / source.name)
            todo.append(source)
    local = sorted(p.name for p in TARGET.glob('*.dll'))
    size = sum(p.stat().st_size for p in TARGET.glob('*.dll')) // 2**20
    print(f'{len(local)} DLL copiées ({size} Mo)')
    print('Laissées au système :', ', '.join(sorted(system)))


if __name__ == '__main__':
    main()
