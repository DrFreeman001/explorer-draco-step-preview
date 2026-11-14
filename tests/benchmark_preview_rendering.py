"""Explicit sequential real-model benchmark; run as a module from repository root."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time
from PySide6.QtWidgets import QApplication
from explorer_preview.preview_rendering import decode_mesh, MeshRenderer

class Counters(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in ['PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage']]

def memory():
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    k = ctypes.WinDLL('kernel32')
    k.GetCurrentProcess.restype = wintypes.HANDLE
    p = ctypes.WinDLL('psapi')
    p.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    if not p.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return {'peak_working_set_mib':round(counters.PeakWorkingSetSize / 2**20, 2), 'peak_private_mib':round(counters.PeakPagefileUsage / 2**20, 2)}

if __name__ == '__main__':
    app = QApplication([])
    source = Path(sys.argv[1])
    dest = Path(sys.argv[2])
    result = {'source':source.name,'source_bytes':source.stat().st_size}
    start = time.perf_counter()
    mesh = decode_mesh(source.read_bytes())
    result.update(decode_seconds=time.perf_counter()-start, vertices=len(mesh.positions), faces=len(mesh.faces), arrays_mib=(mesh.positions.nbytes+mesh.faces.nbytes)/2**20)
    print(json.dumps(result), flush=True)
    start = time.perf_counter()
    with MeshRenderer(mesh) as gpu:
        result.update(upload_seconds=time.perf_counter()-start, driver=gpu.driver)
        del mesh
        start = time.perf_counter()
        im = gpu.render(512,512)
        result['first_render_seconds'] = time.perf_counter()-start
        assert im.save(str(dest))
        times = []
        for angle in [35,40,45,50,55]:
            start = time.perf_counter()
            gpu.render(512,512,yaw=angle)
            times.append(time.perf_counter()-start)
        result['camera_frame_seconds'] = times
        result.update(memory())
    dest.with_suffix('.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)
