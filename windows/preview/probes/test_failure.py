"""Run from repo root after build; verifies native child failure and startup timeout."""
from pathlib import Path
import subprocess
import tempfile
root=Path.cwd();ini=root/'windows/preview/build/preview.ini';previous=ini.read_bytes()
try:
    with tempfile.TemporaryDirectory(prefix='DracoConv-probe-') as tmp:
        script=Path(tmp)/'exit.py';script.write_text('raise SystemExit(19)\n')
        ini.write_text('[helper]\npython='+str(root/'.venv/Scripts/pythonw.exe')+'\nscript='+str(script)+'\n',encoding='utf-16')
        result=subprocess.run([str(root/'windows/preview/build/preview_probe.exe'),'4000'],capture_output=True,text=True,timeout=15)
        print(result.stdout);assert result.returncode==0, 'Helper failure remained at Loading'
        script.write_text('import time; time.sleep(60)\n')
        result=subprocess.run([str(root/'windows/preview/build/preview_probe.exe'),'92000'],capture_output=True,text=True,timeout=98)
        print(result.stdout);assert result.returncode==0, 'Startup timeout remained at Loading'
finally:
    ini.write_bytes(previous)
