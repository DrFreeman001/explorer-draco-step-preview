#include <windows.h>
#include <shobjidl.h>
#include <shlwapi.h>
#include <cstdio>
#include <string>
int wmain(int argc, wchar_t **argv) {
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    HMODULE dll = LoadLibraryW(L"windows\\preview\\build\\DracoPreview.dll");
    if (!dll) return 2;
    auto get = (HRESULT(WINAPI *)(REFCLSID, REFIID, void **))GetProcAddress(dll, "DllGetClassObject");
    CLSID id;
    CLSIDFromString(L"{06B7D1B9-CDEF-4966-8702-8880E7DDB1D9}", &id);
    IClassFactory *f = nullptr;
    IInitializeWithStream *init = nullptr;
    IPreviewHandler *p = nullptr;
    IOleWindow *ow = nullptr;
    IStream *s = nullptr;
    HRESULT hr = get(id, IID_PPV_ARGS(&f));
    if (SUCCEEDED(hr)) hr = f->CreateInstance(nullptr, IID_PPV_ARGS(&init));
    if (SUCCEEDED(hr))
        hr = SHCreateStreamOnFileEx(L"windows\\preview\\cube.drc", STGM_READ | STGM_SHARE_DENY_NONE, 0, FALSE, nullptr,
                                    &s);
    if (SUCCEEDED(hr)) hr = init->Initialize(s, STGM_READ);
    if (SUCCEEDED(hr)) hr = init->QueryInterface(IID_PPV_ARGS(&p));
    HWND host = CreateWindowExW(0, L"STATIC", L"Direct COM test", WS_OVERLAPPEDWINDOW, 0, 0, 400, 400, nullptr, nullptr,
                                GetModuleHandleW(nullptr), nullptr);
    RECT r{0, 0, 400, 400};
    if (SUCCEEDED(hr)) hr = p->SetWindow(host, &r);
    if (SUCCEEDED(hr)) hr = p->DoPreview();
    DWORD duration = argc > 1 ? wcstoul(argv[1], nullptr, 10) : 4000;
    ULONGLONG end = GetTickCount64() + duration;
    while (GetTickCount64() < end) {
        MSG msg;
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        Sleep(20);
    }
    HWND view = nullptr;
    wchar_t status[256]{};
    if (p && SUCCEEDED(p->QueryInterface(IID_PPV_ARGS(&ow)))) {
        ow->GetWindow(&view);
        GetWindowTextW(view, status, 256);
        ow->Release();
    }
    wprintf(L"DoPreview=%08lx status=%ls\n", hr, status);
    bool passed = wcsstr(status, L"indisponible") != nullptr;
    if (p) {
        p->Unload();
        p->Release();
    }
    if (init) init->Release();
    if (s) s->Release();
    if (f) f->Release();
    DestroyWindow(host);
    auto unload = (HRESULT(WINAPI *)())GetProcAddress(dll, "DllCanUnloadNow");
    printf("Unload=%08lx\n", unload());
    CoUninitialize();
    return passed ? 0 : 1;
}
