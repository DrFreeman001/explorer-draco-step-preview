#include <windows.h>
#include <shobjidl.h>
#include <thumbcache.h>
#include <shlwapi.h>
#include <cstdio>
int wmain(int argc, wchar_t **argv) {
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    HMODULE dll = LoadLibraryW(L"windows\\preview\\build\\DracoPreview.dll");
    if (!dll) {
        printf("DLL missing: %lu\n", GetLastError());
        return 1;
    }
    auto get = (HRESULT(WINAPI *)(REFCLSID, REFIID, void **))GetProcAddress(dll, "DllGetClassObject");
    CLSID id;
    CLSIDFromString(L"{47E7A10B-10E8-4648-A385-849CBAB949F0}", &id);
    IClassFactory *f = nullptr;
    HRESULT hr = get(id, IID_PPV_ARGS(&f));
    IInitializeWithStream *init = nullptr;
    if (SUCCEEDED(hr)) hr = f->CreateInstance(nullptr, IID_PPV_ARGS(&init));
    IStream *s = nullptr;
    if (SUCCEEDED(hr))
        hr = SHCreateStreamOnFileEx(argc > 1 ? argv[1] : L"windows\\preview\\cube.drc",
                                    STGM_READ | STGM_SHARE_DENY_NONE, 0, FALSE, nullptr, &s);
    if (SUCCEEDED(hr)) hr = init->Initialize(s, STGM_READ);
    printf("Initialize %08lx\n", hr);
    if (SUCCEEDED(hr)) {
        auto twice = init->Initialize(s, STGM_READ);
        printf("Duplicate %08lx\n", twice);
        if (twice != HRESULT_FROM_WIN32(ERROR_ALREADY_INITIALIZED)) hr = E_FAIL;
    }
    IThumbnailProvider *t = nullptr;
    if (SUCCEEDED(hr)) hr = init->QueryInterface(IID_PPV_ARGS(&t));
    HBITMAP bmp = nullptr;
    WTS_ALPHATYPE alpha;
    if (SUCCEEDED(hr)) hr = t->GetThumbnail(128, &bmp, &alpha);
    printf("Thumbnail %08lx bitmap=%p\n", hr, bmp);
    if (bmp) DeleteObject(bmp);
    if (t) t->Release();
    if (s) s->Release();
    if (init) init->Release();
    if (f) f->Release();
    auto unload = (HRESULT(WINAPI *)())GetProcAddress(dll, "DllCanUnloadNow");
    printf("Unload %08lx\n", unload());
    CoUninitialize();
    return FAILED(hr) ? 2 : 0;
}
