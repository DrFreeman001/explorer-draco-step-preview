"""Reversible per-user registration. Never changes default file opening."""
from pathlib import Path
import argparse
import ctypes
import json
import winreg

THUMB='{47E7A10B-10E8-4648-A385-849CBAB949F0}'
PREVIEW='{06B7D1B9-CDEF-4966-8702-8880E7DDB1D9}'
HERE=Path(__file__).resolve().parent
STATE=HERE/'build/registration.json'


def current(path,name,root=winreg.HKEY_CURRENT_USER):
    try:
        with winreg.OpenKey(root,path) as key: return list(winreg.QueryValueEx(key,name))
    except FileNotFoundError: return None


def install_values(values,state,replace=()):
    """Écrit les valeurs ; celles dont le chemin est dans replace peuvent remplacer une valeur étrangère,
    gardée dans le manifeste et remise au retrait. Une valeur déjà identique n'est pas gardée comme antérieure :
    le retrait la supprime, au lieu de remettre les restes d'une ancienne installation."""
    if state.exists(): raise RuntimeError('Already installed; uninstall first')
    records=[]
    for path,name,value in values:
        previous=current(path,name)
        if previous == [value,winreg.REG_SZ]: previous=None
        if previous is not None and path not in replace:
            raise RuntimeError('Refusing to overwrite existing registration: '+path+' '+name)
        records.append(dict(path=path,name=name,value=value,previous=previous))
    state.write_text(json.dumps(records,indent=2),encoding='utf-8')
    try:
        for row in records:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,row['path']) as key:
                winreg.SetValueEx(key,row['name'],0,winreg.REG_SZ,row['value'])
    except Exception:
        uninstall_values(state)
        raise


def uninstall_values(state):
    if not state.exists(): return
    records=json.loads(state.read_text(encoding='utf-8'))
    for row in reversed(records):
        if current(row['path'],row['name']) != [row['value'],winreg.REG_SZ]: continue
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,row['path'],0,winreg.KEY_SET_VALUE|winreg.KEY_QUERY_VALUE) as key:
            if row['previous'] is None: winreg.DeleteValue(key,row['name'])
            else: winreg.SetValueEx(key,row['name'],0,row['previous'][1],row['previous'][0])
            empty=winreg.QueryInfoKey(key)[:2]==(0,0)
        # Seulement une clé devenue vide : DeleteKey emporterait aussi les valeurs d'autres programmes.
        if empty:
            try: winreg.DeleteKey(winreg.HKEY_CURRENT_USER,row['path'])
            except OSError: pass
    state.unlink()


# Clé d'inscription par extension. Pour STEP, SystemFileAssociations : la clé .step de l'utilisateur appartient
# au trancheur associé, qui la réécrit et y efface les sous-clés shellex (constaté le 13 novembre 2026).
EXTENSIONS={'.drc':'.drc','.step':'SystemFileAssociations\\.step','.stp':'SystemFileAssociations\\.stp',
            '.stl':'SystemFileAssociations\\.stl','.obj':'SystemFileAssociations\\.obj','.3mf':'SystemFileAssociations\\.3mf'}
# Extensions dont on prend la place des gestionnaires existants, avec l'accord de l'utilisateur (14 novembre 2026) :
# miniatures STL de PowerToys (icône générique, pas d'aperçu) et gestionnaire 3MF de Windows (image du trancheur seulement).
# La valeur remplacée est gardée dans le manifeste et remise au retrait.
TAKEOVER={'.stl','.3mf'}
EXTENSION_KEY={'.stl','.obj','.3mf'}


def file_classes(ext):
    """L'extension, ses associations système et les ProgID qui l'ouvrent : un gestionnaire étranger bloque l'installation."""
    classes={ext,'SystemFileAssociations\\'+ext}
    for registration in [current(ext,'',winreg.HKEY_CLASSES_ROOT), current('Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\'+ext+'\\UserChoice','ProgId')]:
        if registration and registration[0]: classes.add(registration[0])
    return classes


def values(replace=None):
    """Lignes à écrire. replace, s'il est donné (un set), reçoit les chemins qui prennent la place d'un gestionnaire."""
    dll=str(HERE/'build/DracoPreview.dll')
    rows=[]
    replace=set() if replace is None else replace
    for clsid,label in [(THUMB,'DracoConv 3D thumbnail'),(PREVIEW,'DracoConv 3D preview')]:
        base='Software\\Classes\\CLSID\\'+clsid
        rows += [(base,'',label),(base+'\\InprocServer32','',dll),(base+'\\InprocServer32','ThreadingModel','Apartment')]
    rows += [('Software\\Classes\\CLSID\\'+PREVIEW,'AppID','{6D2B5079-2F0B-48DD-AB7F-97CEC514D30B}'),('Software\\Microsoft\\Windows\\CurrentVersion\\PreviewHandlers',PREVIEW,'DracoConv 3D preview')]
    for ext,location in EXTENSIONS.items():
        classes=file_classes(ext)
        for handler,clsid in [('{E357FCCD-A995-4576-B01F-234630154E96}',THUMB),('{8895B1C6-B41F-4C1C-A562-0D564250836F}',PREVIEW)]:
            taken=[]
            for file_class in sorted(classes):
                existing=current(file_class+'\\shellex\\'+handler,'',winreg.HKEY_CLASSES_ROOT)
                if existing is not None and existing[0].lower()!=clsid.lower():
                    if ext not in TAKEOVER:
                        raise RuntimeError('Existing '+ext+' handler through '+file_class+': '+str(existing))
                    taken.append(file_class)
            rows.append(('Software\\Classes\\'+location+'\\shellex\\'+handler,'',clsid))
            if ext in EXTENSION_KEY and ext not in taken:
                # Aussi sur la clé de l'extension : elle passe avant le gestionnaire d'une application du Store
                # (3D Viewer pour STL, OBJ et 3MF), qui ignore SystemFileAssociations.
                taken.append(ext)
            for file_class in taken:
                # Même clé que le gestionnaire en place : une valeur de l'utilisateur passe avant celle de la machine.
                path='Software\\Classes\\'+file_class+'\\shellex\\'+handler
                rows.append((path,'',clsid))
                replace.add(path)
    return rows


def main():
    action=argparse.ArgumentParser()
    action.add_argument('action',choices=['install','uninstall','status'])
    command=action.parse_args().action
    if command=='install':
        if not (HERE/'build/DracoPreview.dll').exists(): raise RuntimeError('Build first')
        replace=set()
        install_values(values(replace),STATE,replace)
    elif command=='uninstall': uninstall_values(STATE)
    else:
        print('installed' if STATE.exists() else 'not installed')
        return
    ctypes.windll.shell32.SHChangeNotify(0x08000000,0,None,None)
    print(command+' complete')

if __name__=='__main__': main()
