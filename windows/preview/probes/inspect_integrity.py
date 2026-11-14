"""Read-only process integrity probe; takes process IDs."""
import ctypes
from ctypes import wintypes as w
import sys
k=ctypes.WinDLL('kernel32',use_last_error=True); a=ctypes.WinDLL('advapi32',use_last_error=True)
k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
k.CloseHandle.argtypes=[w.HANDLE]
a.OpenProcessToken.argtypes=[w.HANDLE,w.DWORD,ctypes.POINTER(w.HANDLE)]
a.GetTokenInformation.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.POINTER(w.DWORD)]
a.GetSidSubAuthority.argtypes=[ctypes.c_void_p,w.DWORD];a.GetSidSubAuthority.restype=ctypes.POINTER(w.DWORD)
for pid in map(int,sys.argv[1:]):
    process=k.OpenProcess(0x1000,False,pid);token=w.HANDLE();size=w.DWORD()
    if not process or not a.OpenProcessToken(process,8,ctypes.byref(token)): raise ctypes.WinError(ctypes.get_last_error())
    a.GetTokenInformation(token,25,None,0,ctypes.byref(size));buf=ctypes.create_string_buffer(size.value)
    if not a.GetTokenInformation(token,25,buf,size,ctypes.byref(size)): raise ctypes.WinError(ctypes.get_last_error())
    sid=ctypes.cast(buf,ctypes.POINTER(ctypes.c_void_p))[0];rid=a.GetSidSubAuthority(sid,0)[0]
    print(f'pid={pid} integrity={rid:#x} '+{0x1000:'Low',0x2000:'Medium',0x3000:'High'}.get(rid,'Other'))
    k.CloseHandle(token);k.CloseHandle(process)
