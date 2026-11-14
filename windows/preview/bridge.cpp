#include <windows.h>
#include <shobjidl.h>
#include <shlobj.h>
#include <thumbcache.h>
#include <shlwapi.h>
#include <knownfolders.h>
#include <wincodec.h>
#include <string>
#include <atomic>

static HMODULE module;
static std::atomic<long> objects{0};
static const CLSID thumbId = {0x47e7a10b, 0x10e8, 0x4648, {0xa3, 0x85, 0x84, 0x9c, 0xba, 0xb9, 0x49, 0xf0}};
static const CLSID previewId = {0x06b7d1b9, 0xcdef, 0x4966, {0x87, 0x02, 0x88, 0x80, 0xe7, 0xdd, 0xb1, 0xd9}};
// Textes du volet d'aperçu, en français si l'interface de Windows l'est, en anglais sinon.
static const wchar_t* text(int id) {
    static const bool french = PRIMARYLANGID(GetUserDefaultUILanguage()) == LANG_FRENCH;
    static const wchar_t* const fr[] = {L"Chargement…", L"Aperçu indisponible : chargement interrompu ou limite atteinte.",
                                        L"Un autre aperçu 3D est déjà ouvert dans une autre fenêtre.",
                                        L"Aperçu indisponible : impossible de lancer le processus."};
    static const wchar_t* const en[] = {L"Loading…", L"Preview unavailable: loading interrupted or limit reached.",
                                        L"Another 3D preview is already open in another window.",
                                        L"Preview unavailable: cannot start the helper process."};
    return (french ? fr : en)[id];
}
enum { TEXT_LOADING, TEXT_INTERRUPTED, TEXT_BUSY, TEXT_LAUNCH_FAILED };

static HRESULT error() {
    return HRESULT_FROM_WIN32(GetLastError());
}
static std::wstring quote(const std::wstring &s) {
    return L"\"" + s + L"\"";
}
static void log(const std::wstring &dir, const wchar_t *event, DWORD value = 0) {
    HANDLE f = CreateFileW((dir + L"\\events.log").c_str(), FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           nullptr, OPEN_ALWAYS, 0, nullptr);
    if (f != INVALID_HANDLE_VALUE) {
        char line[160];
        int n = sprintf_s(line, "pid=%lu %ls value=%lu\r\n", GetCurrentProcessId(), event, value);
        DWORD out;
        WriteFile(f, line, n, &out, nullptr);
        CloseHandle(f);
    }
}
class Handler : public IInitializeWithStream,
                public IThumbnailProvider,
                public IPreviewHandler,
                public IObjectWithSite,
                public IOleWindow {
    long refs = 1;
    bool thumbnail;
    std::wstring dir, input;
    HANDLE job = nullptr, process = nullptr, previewGate = nullptr, lease = nullptr;
    ULONGLONG started = 0;
    bool ready = false;
    HWND parent = nullptr, window = nullptr;
    RECT rect{};
    IUnknown *site = nullptr;
    void stopHelper() {
        if (window) KillTimer(window, 1);
        if (job) {
            CloseHandle(job);
            job = nullptr;
        }
        if (process) {
            WaitForSingleObject(process, 1500);
            CloseHandle(process);
            process = nullptr;
        }
        if (previewGate) {
            ReleaseMutex(previewGate);
            CloseHandle(previewGate);
            previewGate = nullptr;
        }
    }
    static LRESULT CALLBACK procedure(HWND hwnd, UINT message, WPARAM wp, LPARAM lp) {
        auto self = reinterpret_cast<Handler *>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
        if (message == WM_NCCREATE) {
            self = static_cast<Handler *>(reinterpret_cast<CREATESTRUCTW *>(lp)->lpCreateParams);
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
        }
        if (self && message == WM_TIMER) {
            self->monitor();
            return 0;
        }
        if (self && message == WM_SETFOCUS) {
            HWND child = ::GetWindow(hwnd, GW_CHILD);
            if (child) ::SetFocus(child);
            return 0;
        }
        if (self && message == WM_APP + 1) {
            MSG key{};
            key.hwnd = hwnd;
            key.message = WM_KEYDOWN;
            key.wParam = VK_TAB;
            key.lParam = lp;
            self->TranslateAccelerator(&key);
            return 0;
        }
        if (message == WM_PAINT) {
            PAINTSTRUCT ps;
            HDC dc = BeginPaint(hwnd, &ps);
            RECT area;
            GetClientRect(hwnd, &area);
            FillRect(dc, &area, (HBRUSH)(COLOR_WINDOW + 1));
            wchar_t text[256];
            GetWindowTextW(hwnd, text, 256);
            area.left += 12;
            area.top += 12;
            DrawTextW(dc, text, -1, &area, DT_WORDBREAK);
            EndPaint(hwnd, &ps);
            return 0;
        }
        if (message == WM_SETTEXT) {
            LRESULT result = DefWindowProcW(hwnd, message, wp, lp);
            InvalidateRect(hwnd, nullptr, TRUE);
            return result;
        }
        return DefWindowProcW(hwnd, message, wp, lp);
    }
    void monitor() {
        if (!process) return;
        if (GetFileAttributesW((dir + L"\\ready").c_str()) != INVALID_FILE_ATTRIBUTES) ready = true;
        if (WaitForSingleObject(process, 0) == WAIT_OBJECT_0 || (!ready && GetTickCount64() - started > 90000)) {
            stopHelper();
            SetWindowTextW(window, text(TEXT_INTERRUPTED));
        }
    }
    void cleanup() {
        stopHelper();
        if (job) {
            CloseHandle(job);
            job = nullptr;
        }
        if (process) {
            WaitForSingleObject(process, 1500);
            CloseHandle(process);
            process = nullptr;
        }
        if (window) {
            DestroyWindow(window);
            window = nullptr;
        }
        if (!input.empty()) {
            DeleteFileW(input.c_str());
            DeleteFileW((dir + L"\\model.mesh").c_str());
            DeleteFileW((dir + L"\\model.mesh.part").c_str());
            DeleteFileW((dir + L"\\thumb.png").c_str());
            DeleteFileW((dir + L"\\ready").c_str());
            DeleteFileW((dir + L"\\events.log").c_str());
            if (lease) {
                CloseHandle(lease);
                lease = nullptr;
            }
            DeleteFileW((dir + L"\\lease.v1").c_str());
            RemoveDirectoryW(dir.c_str());
            input.clear();
        }
    }
    HRESULT launch(const std::wstring &args) {
        wchar_t config[MAX_PATH];
        GetModuleFileNameW(module, config, MAX_PATH);
        PathRemoveFileSpecW(config);
        PathAppendW(config, L"preview.ini");
        wchar_t python[32768], script[32768];
        GetPrivateProfileStringW(L"helper", L"python", L"", python, 32768, config);
        GetPrivateProfileStringW(L"helper", L"script", L"", script, 32768, config);
        if (!*python || !*script) return E_UNEXPECTED;
        if (!thumbnail) {
            previewGate = CreateMutexW(nullptr, FALSE, L"Local\\DracoConvPreview-06B7D1B9");
            if (!previewGate) return error();
            DWORD wait = WaitForSingleObject(previewGate, 0);
            if (wait != WAIT_OBJECT_0 && wait != WAIT_ABANDONED) {
                CloseHandle(previewGate);
                previewGate = nullptr;
                return HRESULT_FROM_WIN32(ERROR_BUSY);
            }
        }
        job = CreateJobObjectW(nullptr, nullptr);
        if (!job) return error();
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_PROCESS_MEMORY |
                                                  JOB_OBJECT_LIMIT_JOB_MEMORY | JOB_OBJECT_LIMIT_ACTIVE_PROCESS;
        limits.ProcessMemoryLimit = 3072ull * 1024 * 1024;
        limits.JobMemoryLimit = 3072ull * 1024 * 1024;
        limits.BasicLimitInformation.ActiveProcessLimit = 4;
        if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits))) return error();
        std::wstring cmd = quote(python) + L" -I -B " + quote(script) + L" --input " + quote(input) + L" " + args;
        STARTUPINFOW si{};
        si.cb = sizeof(si);
        PROCESS_INFORMATION pi{};
        if (!CreateProcessW(python, cmd.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW | CREATE_SUSPENDED, nullptr,
                            dir.c_str(), &si, &pi)) {
            log(dir, L"CreateProcess", GetLastError());
            return error();
        }
        process = pi.hProcess;
        if (!AssignProcessToJobObject(job, process)) {
            DWORD code = GetLastError();
            TerminateProcess(process, 1);
            CloseHandle(pi.hThread);
            return HRESULT_FROM_WIN32(code);
        }
        if (ResumeThread(pi.hThread) == DWORD(-1)) {
            DWORD code = GetLastError();
            CloseHandle(pi.hThread);
            stopHelper();
            return HRESULT_FROM_WIN32(code);
        }
        CloseHandle(pi.hThread);
        log(dir, L"helper-start", pi.dwProcessId);
        return S_OK;
    }

public:
    Handler(bool t) : thumbnail(t) { ++objects; }
    ~Handler() {
        cleanup();
        if (site) site->Release();
        --objects;
    }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void **out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (iid == IID_IUnknown || iid == __uuidof(IInitializeWithStream))
            *out = static_cast<IInitializeWithStream *>(this);
        else if (thumbnail && iid == __uuidof(IThumbnailProvider))
            *out = static_cast<IThumbnailProvider *>(this);
        else if (!thumbnail && iid == __uuidof(IPreviewHandler))
            *out = static_cast<IPreviewHandler *>(this);
        else if (!thumbnail && iid == __uuidof(IObjectWithSite))
            *out = static_cast<IObjectWithSite *>(this);
        else if (!thumbnail && iid == __uuidof(IOleWindow))
            *out = static_cast<IOleWindow *>(this);
        if (!*out) return E_NOINTERFACE;
        AddRef();
        return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return InterlockedIncrement(&refs); }
    ULONG STDMETHODCALLTYPE Release() override {
        long n = InterlockedDecrement(&refs);
        if (!n) delete this;
        return n;
    }
    HRESULT STDMETHODCALLTYPE Initialize(IStream *stream, DWORD mode) override {
        if (!stream) return E_POINTER;
        if (!input.empty()) return HRESULT_FROM_WIN32(ERROR_ALREADY_INITIALIZED);
        if (mode & STGM_READWRITE) return STG_E_ACCESSDENIED;
        PWSTR low = nullptr;
        HRESULT hr = SHGetKnownFolderPath(FOLDERID_LocalAppDataLow, 0, nullptr, &low);
        if (FAILED(hr)) return hr;
        std::wstring base = std::wstring(low) + L"\\DracoConvPreview";
        CoTaskMemFree(low);
        CreateDirectoryW(base.c_str(), nullptr);
        GUID id;
        CoCreateGuid(&id);
        wchar_t name[40];
        StringFromGUID2(id, name, 40);
        dir = base + L"\\" + name;
        if (!CreateDirectoryW(dir.c_str(), nullptr)) return error();
        input = dir + L"\\input.drc";
        // Bail exclusif tenu jusqu'au nettoyage. S'il peut être rouvert, son propriétaire est mort (plantage de l'hôte)
        // et le dossier est ramassé par l'auxiliaire suivant : voir collect_stale dans explorer_preview/preview_temp.py.
        static const char marker[] = "DracoConvPreview lease v1\n";
        DWORD marked = 0;
        lease = CreateFileW((dir + L"\\lease.v1").c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, CREATE_NEW,
                            FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
        if (lease == INVALID_HANDLE_VALUE) lease = nullptr;
        if (!lease || !WriteFile(lease, marker, sizeof(marker) - 1, &marked, nullptr) || marked != sizeof(marker) - 1) {
            hr = error();
            cleanup();
            return hr;
        }
        HANDLE f = CreateFileW(input.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_ATTRIBUTE_TEMPORARY, nullptr);
        if (f == INVALID_HANDLE_VALUE) {
            hr = error();
            cleanup();
            return hr;
        }
        char buffer[65536];
        ULONG got = 0;
        size_t total = 0;
        do {
            hr = stream->Read(buffer, sizeof(buffer), &got);
            if (FAILED(hr)) break;
            total += got;
            if (total > 200 * 1024 * 1024) {
                hr = HRESULT_FROM_WIN32(ERROR_FILE_TOO_LARGE);
                break;
            }
            DWORD written;
            if (got && (!WriteFile(f, buffer, got, &written, nullptr) || written != got)) {
                hr = error();
                break;
            }
        } while (got);
        CloseHandle(f);
        if (FAILED(hr) || !total) {
            cleanup();
            return FAILED(hr) ? hr : E_INVALIDARG;
        }
        log(dir, L"initialized");
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetThumbnail(UINT cx, HBITMAP *out, WTS_ALPHATYPE *alpha) override {
        if (!out || !alpha) return E_POINTER;
        *out = nullptr;
        *alpha = WTSAT_UNKNOWN;
        if (input.empty()) return E_UNEXPECTED;
        HANDLE mutex = CreateMutexW(nullptr, FALSE, L"Local\\DracoConvThumbnail-47E7A10B");
        if (!mutex) return error();
        DWORD wait = WaitForSingleObject(mutex, 0);
        if (wait != WAIT_OBJECT_0 && wait != WAIT_ABANDONED) {
            CloseHandle(mutex);
            return HRESULT_FROM_WIN32(ERROR_BUSY);
        }
        std::wstring output = dir + L"\\thumb.png";
        HRESULT hr = launch(L"--output " + quote(output) + L" --size " + std::to_wstring(cx));
        if (SUCCEEDED(hr)) {
            if (WaitForSingleObject(process, 90000) != WAIT_OBJECT_0)
                hr = HRESULT_FROM_WIN32(ERROR_TIMEOUT);
            else {
                DWORD code;
                GetExitCodeProcess(process, &code);
                if (code) {
                    printf("Helper exit %lu\n", code);
                    hr = E_FAIL;
                }
            }
        }
        if (SUCCEEDED(hr)) {
            IWICImagingFactory *factory = nullptr;
            IWICBitmapDecoder *decoder = nullptr;
            IWICBitmapFrameDecode *frame = nullptr;
            IWICFormatConverter *converter = nullptr;
            hr = CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&factory));
            if (SUCCEEDED(hr))
                hr = factory->CreateDecoderFromFilename(output.c_str(), nullptr, GENERIC_READ,
                                                        WICDecodeMetadataCacheOnLoad, &decoder);
            if (SUCCEEDED(hr)) hr = decoder->GetFrame(0, &frame);
            if (SUCCEEDED(hr)) hr = factory->CreateFormatConverter(&converter);
            if (SUCCEEDED(hr))
                hr = converter->Initialize(frame, GUID_WICPixelFormat32bppPBGRA, WICBitmapDitherTypeNone, nullptr, 0,
                                           WICBitmapPaletteTypeCustom);
            UINT w = 0, h = 0;
            if (SUCCEEDED(hr)) hr = converter->GetSize(&w, &h);
            if (SUCCEEDED(hr)) {
                BITMAPINFO info{};
                info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
                info.bmiHeader.biWidth = w;
                info.bmiHeader.biHeight = -LONG(h);
                info.bmiHeader.biPlanes = 1;
                info.bmiHeader.biBitCount = 32;
                void *bits = nullptr;
                *out = CreateDIBSection(nullptr, &info, DIB_RGB_COLORS, &bits, nullptr, 0);
                if (!*out)
                    hr = error();
                else
                    hr = converter->CopyPixels(nullptr, w * 4, w * h * 4, (BYTE *)bits);
                if (SUCCEEDED(hr))
                    *alpha = WTSAT_ARGB;
                else if (*out) {
                    DeleteObject(*out);
                    *out = nullptr;
                }
            }
            if (converter) converter->Release();
            if (frame) frame->Release();
            if (decoder) decoder->Release();
            if (factory) factory->Release();
        }
        ReleaseMutex(mutex);
        CloseHandle(mutex);
        cleanup();
        return hr;
    }
    HRESULT STDMETHODCALLTYPE SetWindow(HWND hwnd, const RECT *r) override {
        if (!r) return E_POINTER;
        parent = hwnd;
        rect = *r;
        if (window) SetParent(window, parent);
        return SetRect(r);
    }
    HRESULT STDMETHODCALLTYPE SetRect(const RECT *r) override {
        if (!r) return E_POINTER;
        rect = *r;
        if (window) MoveWindow(window, rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top, TRUE);
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE DoPreview() override {
        if (!parent || input.empty()) return E_UNEXPECTED;
        if (window) return S_FALSE;
        WNDCLASSW cls{};
        cls.lpfnWndProc = procedure;
        cls.hInstance = module;
        cls.lpszClassName = L"DracoConvPreviewContainer";
        cls.hCursor = LoadCursorW(nullptr, IDC_ARROW);
        if (!RegisterClassW(&cls) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS) return error();
        window = CreateWindowExW(0, cls.lpszClassName, text(TEXT_LOADING),
                                 WS_CHILD | WS_VISIBLE | WS_CLIPCHILDREN | WS_TABSTOP, rect.left, rect.top,
                                 rect.right - rect.left, rect.bottom - rect.top, parent, nullptr, module, this);
        if (!window) return error();
        HRESULT hr = launch(L"--parent " + std::to_wstring((uintptr_t)window));
        if (hr == HRESULT_FROM_WIN32(ERROR_BUSY)) {
            SetWindowTextW(window, text(TEXT_BUSY));
            return S_OK;
        }
        if (FAILED(hr)) {
            stopHelper();
            SetWindowTextW(window, text(TEXT_LAUNCH_FAILED));
        } else {
            started = GetTickCount64();
            ready = false;
            SetTimer(window, 1, 200, nullptr);
        }
        return hr;
    }
    HRESULT STDMETHODCALLTYPE Unload() override {
        cleanup();
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE SetFocus() override {
        if (!window) return E_FAIL;
        HWND child = ::GetWindow(window, GW_CHILD);
        ::SetFocus(child ? child : window);
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE QueryFocus(HWND *out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (!window) return E_FAIL;
        HWND child = ::GetWindow(window, GW_CHILD);
        GUITHREADINFO info{};
        info.cbSize = sizeof(info);
        if (!GetGUIThreadInfo(GetWindowThreadProcessId(child ? child : window, nullptr), &info)) return error();
        *out = info.hwndFocus;
        return *out ? S_OK : S_FALSE;
    }
    HRESULT STDMETHODCALLTYPE TranslateAccelerator(MSG *msg) override {
        IPreviewHandlerFrame *frame = nullptr;
        HRESULT hr = S_FALSE;
        if (site && SUCCEEDED(site->QueryInterface(IID_PPV_ARGS(&frame)))) {
            hr = frame->TranslateAccelerator(msg);
            frame->Release();
        }
        return hr;
    }
    HRESULT STDMETHODCALLTYPE SetSite(IUnknown *s) override {
        if (s) s->AddRef();
        if (site) site->Release();
        site = s;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetSite(REFIID iid, void **out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        return site ? site->QueryInterface(iid, out) : E_FAIL;
    }
    HRESULT STDMETHODCALLTYPE GetWindow(HWND *out) override {
        if (!out) return E_POINTER;
        *out = window;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE ContextSensitiveHelp(BOOL) override { return E_NOTIMPL; }
};
class Factory : public IClassFactory {
    long refs = 1;
    bool thumbnail;

public:
    Factory(bool t) : thumbnail(t) { ++objects; }
    ~Factory() { --objects; }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void **out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (iid != IID_IUnknown && iid != IID_IClassFactory) return E_NOINTERFACE;
        *out = this;
        AddRef();
        return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return InterlockedIncrement(&refs); }
    ULONG STDMETHODCALLTYPE Release() override {
        long n = InterlockedDecrement(&refs);
        if (!n) delete this;
        return n;
    }
    HRESULT STDMETHODCALLTYPE CreateInstance(IUnknown *outer, REFIID iid, void **out) override {
        if (outer) return CLASS_E_NOAGGREGATION;
        auto obj = new Handler(thumbnail);
        HRESULT hr = obj->QueryInterface(iid, out);
        obj->Release();
        return hr;
    }
    HRESULT STDMETHODCALLTYPE LockServer(BOOL lock) override {
        objects += lock ? 1 : -1;
        return S_OK;
    }
};
extern "C" HRESULT WINAPI DllGetClassObject(REFCLSID cls, REFIID iid, void **out) {
    if (cls != thumbId && cls != previewId) return CLASS_E_CLASSNOTAVAILABLE;
    auto f = new Factory(cls == thumbId);
    HRESULT hr = f->QueryInterface(iid, out);
    f->Release();
    return hr;
}
extern "C" HRESULT WINAPI DllCanUnloadNow() {
    if (objects == 0) {
        UnregisterClassW(L"DracoConvPreviewContainer", module);
        return S_OK;
    }
    return S_FALSE;
}
BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        module = instance;
        DisableThreadLibraryCalls(instance);
    }
    return TRUE;
}
