// Refait les miniatures 3D d'un dossier (clic droit « Refaire les miniatures 3D »), sans toucher aux fichiers.
// Usage : refresh_thumbnails.exe <dossier> [/s]   (/s : sous-dossiers compris)
// Demande à Windows une extraction forcée pour chaque fichier pris en charge, aux tailles d'icône courantes,
// puis signale le changement à l'Explorateur. Les dates des fichiers ne changent pas.
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shlobj.h>
#include <shobjidl.h>
#include <thumbcache.h>
#include <string>
#include <vector>
#include <cwctype>

static const wchar_t* const EXTENSIONS[] = {L".drc", L".step", L".stp", L".stl", L".obj", L".3mf",
                                            L".ply", L".glb", L".gltf", L".amf"};

static bool supported(const std::wstring& name) {
    size_t dot = name.find_last_of(L'.');
    if (dot == std::wstring::npos) return false;
    std::wstring ext = name.substr(dot);
    for (wchar_t& c : ext) c = static_cast<wchar_t>(std::towlower(c));
    for (const wchar_t* known : EXTENSIONS)
        if (ext == known) return true;
    return false;
}

static void collect(const std::wstring& folder, bool recursive, std::vector<std::wstring>& files) {
    WIN32_FIND_DATAW data;
    HANDLE find = FindFirstFileW((folder + L"\\*").c_str(), &data);
    if (find == INVALID_HANDLE_VALUE) return;
    do {
        std::wstring name = data.cFileName;
        if (name == L"." || name == L"..") continue;
        if (data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) continue;  // pas de jonctions ni de liens
        std::wstring path = folder + L"\\" + name;
        if (data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            if (recursive) collect(path, true, files);
        } else if (supported(name)) {
            files.push_back(path);
        }
    } while (FindNextFileW(find, &data));
    FindClose(find);
}

int wmain(int argc, wchar_t** argv) {
    if (argc < 2) return 1;
    bool recursive = argc > 2 && std::wstring(argv[2]) == L"/s";
    if (FAILED(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED))) return 2;
    std::vector<std::wstring> files;
    collect(argv[1], recursive, files);
    IThumbnailCache* cache = nullptr;
    if (FAILED(CoCreateInstance(CLSID_LocalThumbnailCache, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&cache)))) {
        CoUninitialize();
        return 3;
    }
    int refreshed = 0;
    for (const std::wstring& file : files) {
        IShellItem* item = nullptr;
        if (FAILED(SHCreateItemFromParsingName(file.c_str(), nullptr, IID_PPV_ARGS(&item)))) continue;
        bool done = false;
        for (UINT size : {96u, 256u, 1024u}) {
            // L'extension n'accepte qu'une miniature à la fois : on réessaie un peu si elle est occupée.
            for (int attempt = 0; attempt < 20; ++attempt) {
                ISharedBitmap* bitmap = nullptr;
                HRESULT hr = cache->GetThumbnail(item, size, WTS_FORCEEXTRACTION, &bitmap, nullptr, nullptr);
                if (bitmap) bitmap->Release();
                if (hr != HRESULT_FROM_WIN32(ERROR_BUSY)) {
                    done = done || SUCCEEDED(hr);
                    break;
                }
                Sleep(250);
            }
        }
        item->Release();
        if (done) {
            ++refreshed;
            SHChangeNotify(SHCNE_UPDATEITEM, SHCNF_PATHW | SHCNF_FLUSHNOWAIT, file.c_str(), nullptr);
        }
    }
    SHChangeNotify(SHCNE_UPDATEDIR, SHCNF_PATHW | SHCNF_FLUSH, argv[1], nullptr);
    cache->Release();
    CoUninitialize();
    return refreshed == static_cast<int>(files.size()) ? 0 : 4;
}
