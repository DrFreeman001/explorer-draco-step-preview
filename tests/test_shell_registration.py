import importlib.util
from pathlib import Path
import uuid
import winreg
import pytest

spec=importlib.util.spec_from_file_location('preview_register',Path(__file__).parents[1]/'windows/preview/register.py')
register=importlib.util.module_from_spec(spec)
spec.loader.exec_module(register)

def test_registry_refuses_foreign_and_restores(tmp_path):
    base='Software\\DracoConvTest\\'+str(uuid.uuid4())
    values=[(base,'handler','ours')]
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,base) as key: winreg.SetValueEx(key,'handler',0,winreg.REG_SZ,'foreign')
    with pytest.raises(RuntimeError): register.install_values(values,tmp_path/'state.json')
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,base,0,winreg.KEY_SET_VALUE) as key: winreg.DeleteValue(key,'handler')
    register.install_values(values,tmp_path/'state.json')
    register.uninstall_values(tmp_path/'state.json')
    with pytest.raises(FileNotFoundError):
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,base) as key: winreg.QueryValueEx(key,'handler')
    try: winreg.DeleteKey(winreg.HKEY_CURRENT_USER,base)
    except FileNotFoundError: pass

def test_effective_progid_handler_is_not_overwritten(monkeypatch):
    def read(path,name,root=winreg.HKEY_CURRENT_USER):
        if path.endswith('UserChoice') and name=='ProgId': return ['Foreign.App',winreg.REG_SZ]
        if path.startswith('Foreign.App\\shellex\\'): return ['{foreign}',winreg.REG_SZ]
        return None
    monkeypatch.setattr(register,'current',read)
    with pytest.raises(RuntimeError,match='handler'): register.values()


def test_default_progid_handler_is_not_overwritten(monkeypatch):
    def read(path,name,root=winreg.HKEY_CURRENT_USER):
        if path=='.drc': return ['Foreign.Default',winreg.REG_SZ]
        if path.startswith('Foreign.Default\\shellex\\'): return ['{foreign}',winreg.REG_SZ]
        return None
    monkeypatch.setattr(register,'current',read)
    with pytest.raises(RuntimeError,match='handler'): register.values()


def test_step_extensions_get_both_handlers(monkeypatch):
    monkeypatch.setattr(register,'current',lambda path,name,root=winreg.HKEY_CURRENT_USER: None)
    rows={(path,value) for path,name,value in register.values() if '\\shellex\\' in path}
    # STEP passe par SystemFileAssociations : un trancheur réécrit HKCU\Software\Classes\.step et y efface shellex.
    for base in ('Software\\Classes\\.drc','Software\\Classes\\SystemFileAssociations\\.step','Software\\Classes\\SystemFileAssociations\\.stp'):
        assert (base+'\\shellex\\{E357FCCD-A995-4576-B01F-234630154E96}',register.THUMB) in rows
        assert (base+'\\shellex\\{8895B1C6-B41F-4C1C-A562-0D564250836F}',register.PREVIEW) in rows
    assert not any(path.startswith('Software\\Classes\\.step') for path,_ in rows)


def test_existing_system_association_handler_is_not_overwritten(monkeypatch):
    def read(path,name,root=winreg.HKEY_CURRENT_USER):
        if path.startswith('SystemFileAssociations\\.stp\\shellex\\'): return ['{foreign}',winreg.REG_SZ]
        return None
    monkeypatch.setattr(register,'current',read)
    with pytest.raises(RuntimeError,match='handler'): register.values()


def test_step_progid_handler_is_not_overwritten(monkeypatch):
    def read(path,name,root=winreg.HKEY_CURRENT_USER):
        if path=='.step': return ['Orca.Slicer.1',winreg.REG_SZ]
        if path.startswith('Orca.Slicer.1\\shellex\\'): return ['{foreign}',winreg.REG_SZ]
        return None
    monkeypatch.setattr(register,'current',read)
    with pytest.raises(RuntimeError,match='handler'): register.values()


def test_stl_and_3mf_take_over_existing_handlers(monkeypatch):
    def read(path,name,root=winreg.HKEY_CURRENT_USER):
        if path=='.stl\\shellex\\{E357FCCD-A995-4576-B01F-234630154E96}': return ['{powertoys}',winreg.REG_SZ]
        if path=='.3mf\\shellex\\{8895B1C6-B41F-4C1C-A562-0D564250836F}': return ['{windows}',winreg.REG_SZ]
        return None
    monkeypatch.setattr(register,'current',read)
    replace=set()
    rows={(path,value) for path,name,value in register.values(replace)}
    assert ('Software\\Classes\\.stl\\shellex\\{E357FCCD-A995-4576-B01F-234630154E96}',register.THUMB) in rows
    assert ('Software\\Classes\\.3mf\\shellex\\{8895B1C6-B41F-4C1C-A562-0D564250836F}',register.PREVIEW) in rows
    # Les deux gestionnaires étrangers sont remplacés ; STL, OBJ et 3MF sont aussi inscrits sur la clé de l'extension.
    assert replace=={'Software\\Classes\\'+ext+'\\shellex\\'+handler for ext in ('.stl','.obj','.3mf')
                     for handler in ('{E357FCCD-A995-4576-B01F-234630154E96}','{8895B1C6-B41F-4C1C-A562-0D564250836F}')}
    for ext in ('.stl','.obj','.3mf'):
        assert ('Software\\Classes\\SystemFileAssociations\\'+ext+'\\shellex\\{8895B1C6-B41F-4C1C-A562-0D564250836F}',register.PREVIEW) in rows
    assert not any(path.startswith('Software\\Classes\\.drc\\') and path in replace for path,_ in rows)


def test_replaced_value_is_restored_and_own_leftover_is_not(tmp_path):
    base='Software\\DracoConvTest\\'+str(uuid.uuid4())
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,base) as key:
        winreg.SetValueEx(key,'foreign',0,winreg.REG_SZ,'theirs')
        winreg.SetValueEx(key,'leftover',0,winreg.REG_SZ,'ours')
    rows=[(base,'foreign','ours'),(base,'leftover','ours')]
    with pytest.raises(RuntimeError): register.install_values(rows,tmp_path/'s.json')
    register.install_values(rows,tmp_path/'s.json',replace={base})
    assert register.current(base,'foreign')==['ours',winreg.REG_SZ]
    register.uninstall_values(tmp_path/'s.json')
    assert register.current(base,'foreign')==['theirs',winreg.REG_SZ]
    assert register.current(base,'leftover') is None  # une valeur déjà à nous n'est pas « remise »
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER,base)
