#include <windows.h>
#include <shobjidl.h>
#include <thumbcache.h>
#include <cstdio>
int wmain(int argc, wchar_t **argv) {
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    IShellItem *item = nullptr;
    IThumbnailCache *cache = nullptr;
    ISharedBitmap *bitmap = nullptr;
    WTS_CACHEFLAGS flags{};
    WTS_THUMBNAILID id{};
    HRESULT hr = argc > 1 ? SHCreateItemFromParsingName(argv[1], nullptr, IID_PPV_ARGS(&item)) : E_INVALIDARG;
    if (SUCCEEDED(hr))
        hr = CoCreateInstance(CLSID_LocalThumbnailCache, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&cache));
    if (SUCCEEDED(hr)) hr = cache->GetThumbnail(item, 256, WTS_FORCEEXTRACTION, &bitmap, &flags, &id);
    printf("Shell thumbnail cache HRESULT=%08lx bitmap=%p\n", hr, bitmap);
    if (bitmap) bitmap->Release();
    if (cache) cache->Release();
    if (item) item->Release();
    CoUninitialize();
    return FAILED(hr);
}
