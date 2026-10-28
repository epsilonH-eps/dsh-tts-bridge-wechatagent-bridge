// WeChat 4.1.10.27 原生语音条发送。
// 这里不依赖 version.dll 的 HTTP 路由，也不依赖 Frida；由 hook 自己调用
// Weixin.dll 的 send_message，构造一条 type=34 的语音消息。
#include "voice_sender.h"
#include "global.h"

#include <Windows.h>
#include <objbase.h>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <vector>

namespace {
constexpr uintptr_t VOICE_VTABLE = 0x8DCFF98;
constexpr uintptr_t VOICE_VTABLE2 = 0x8DD0028;
constexpr uintptr_t CREATE_PARAM2 = 0xDF40;
constexpr uintptr_t SEND_MESSAGE = 0x1677A30;
constexpr uintptr_t PARAM1_VTABLE = 0x84EC9C8;
constexpr uintptr_t PARAM2_1 = 0x8595F58;
constexpr uintptr_t PARAM2_2 = 0x8595E98;
constexpr uintptr_t PARAM2_3 = 0x8595DD8;
constexpr uintptr_t PARAM2_GLOBAL = 0xA0CE0B0;

#pragma pack(push, 1)
struct WxString {
    union { char inline_buf[16]; char* heap_buf; };
    uint64_t length;
    uint64_t cap;
};
#pragma pack(pop)
static_assert(sizeof(WxString) == 0x20, "WxString layout");

uint64_t CalcCap(uint64_t length) {
    const uint64_t need = length + 1;
    return ((need + 0xF) & ~0xFULL) - 1;
}

void SetWxStringRaw(WxString* dst, const char* src, size_t length) {
    std::memset(dst, 0, sizeof(*dst));
    dst->length = length;
    if (length < 16) {
        std::memcpy(dst->inline_buf, src, length);
        dst->cap = 0xF;
        return;
    }
    char* buf = static_cast<char*>(HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, length + 1));
    if (!buf) return;
    std::memcpy(buf, src, length);
    dst->heap_buf = buf;
    dst->cap = CalcCap(length);
}

std::string GuidString() {
    GUID guid{};
    CoCreateGuid(&guid);
    char buf[64]{};
    std::snprintf(buf, sizeof(buf),
        "%08x-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x",
        guid.Data1, guid.Data2, guid.Data3,
        guid.Data4[0], guid.Data4[1], guid.Data4[2], guid.Data4[3],
        guid.Data4[4], guid.Data4[5], guid.Data4[6], guid.Data4[7]);
    return std::string(buf);
}

// 这个函数里只能出现 POD/指针，不能有 C++ 析构对象，否则 MSVC 会拒绝 __try。
bool CallSendRaw(uintptr_t base, const char* target, size_t targetLen,
                 const unsigned char* silk, size_t silkLen, uint64_t durationMs,
                 const char* guid, size_t guidLen) {
    __try {
        HANDLE heap = GetProcessHeap();
        auto* msg = static_cast<unsigned char*>(HeapAlloc(heap, HEAP_ZERO_MEMORY, 0x800));
        if (!msg) return false;
        auto* w = reinterpret_cast<uint64_t*>(msg);
        w[0] = base + VOICE_VTABLE;
        w[1] = 0x0000000200000001ULL;
        w[2] = base + VOICE_VTABLE2;
        *reinterpret_cast<uint64_t*>(msg + 0x18) = reinterpret_cast<uint64_t>(msg + 0x10);
        *reinterpret_cast<uint64_t*>(msg + 0x20) = reinterpret_cast<uint64_t>(msg);
        const uint64_t caps[] = {0x40, 0x60, 0x80, 0xA0, 0x130, 0x170, 0x190, 0x1B8,
                                 0x668, 0x688, 0x6B0, 0x6F0, 0x710, 0x770};
        for (auto off : caps) *reinterpret_cast<uint64_t*>(msg + off) = 0xF;
        *reinterpret_cast<uint64_t*>(msg + 0xA8) = 0x0000000100000000ULL;
        *reinterpret_cast<uint64_t*>(msg + 0xB0) = 0x0000000700000000ULL;
        SetWxStringRaw(reinterpret_cast<WxString*>(msg + 0xC0), target, targetLen);
        *reinterpret_cast<uint64_t*>(msg + 0x108) = 7;
        *reinterpret_cast<uint64_t*>(msg + 0x150) = 7;
        *reinterpret_cast<uint64_t*>(msg + 0xE8) = 34;
        SetWxStringRaw(reinterpret_cast<WxString*>(msg + 0x6B8), guid, guidLen);

        auto* silkCopy = static_cast<unsigned char*>(HeapAlloc(heap, HEAP_ZERO_MEMORY, silkLen + 64));
        if (!silkCopy) return false;
        std::memcpy(silkCopy, silk, silkLen);
        *reinterpret_cast<uint64_t*>(msg + 0x718) = reinterpret_cast<uint64_t>(silkCopy);
        *reinterpret_cast<uint64_t*>(msg + 0x728) = silkLen;
        *reinterpret_cast<uint64_t*>(msg + 0x730) = silkLen + 16;
        *reinterpret_cast<uint64_t*>(msg + 0x738) = durationMs;
        *reinterpret_cast<uint64_t*>(msg + 0x740) = 0x0000000300000004ULL;
        *reinterpret_cast<uint64_t*>(msg + 0x748) = 30000;

        auto* s1 = static_cast<unsigned char*>(HeapAlloc(heap, HEAP_ZERO_MEMORY, 0x20));
        auto* s2 = static_cast<unsigned char*>(HeapAlloc(heap, HEAP_ZERO_MEMORY, 0x28));
        if (!s1 || !s2) return false;
        *reinterpret_cast<uint64_t*>(s1) = reinterpret_cast<uint64_t>(msg + 0x10);
        *reinterpret_cast<uint64_t*>(s1 + 8) = reinterpret_cast<uint64_t>(msg);
        *reinterpret_cast<uint64_t*>(s1 + 0x10) = 0;
        *reinterpret_cast<uint64_t*>(s1 + 0x18) = 0;
        *reinterpret_cast<uint64_t*>(s2) = base + PARAM1_VTABLE;
        *reinterpret_cast<uint64_t*>(s2 + 8) = reinterpret_cast<uint64_t>(s1);
        *reinterpret_cast<uint64_t*>(s2 + 0x10) = reinterpret_cast<uint64_t>(s1 + 0x10);
        *reinterpret_cast<uint64_t*>(s2 + 0x18) = reinterpret_cast<uint64_t>(s1 + 0x10);
        *reinterpret_cast<uint64_t*>(s2 + 0x20) = 1;

        auto* out = static_cast<unsigned char*>(HeapAlloc(heap, HEAP_ZERO_MEMORY, 0xE8));
        auto* p2 = static_cast<unsigned char*>(HeapAlloc(heap, HEAP_ZERO_MEMORY, 0x40));
        auto* p3 = static_cast<unsigned char*>(HeapAlloc(heap, HEAP_ZERO_MEMORY, 0x40));
        auto* p4 = static_cast<unsigned char*>(HeapAlloc(heap, HEAP_ZERO_MEMORY, 0x40));
        auto* buf = static_cast<unsigned char*>(HeapAlloc(heap, HEAP_ZERO_MEMORY, 0x80));
        if (!out || !p2 || !p3 || !p4 || !buf) return false;
        *reinterpret_cast<uint64_t*>(p2) = base + PARAM2_1;
        *reinterpret_cast<uint64_t*>(p2 + 0x38) = reinterpret_cast<uint64_t>(p2);
        *reinterpret_cast<uint64_t*>(p3) = base + PARAM2_2;
        *reinterpret_cast<uint64_t*>(p3 + 0x38) = reinterpret_cast<uint64_t>(p3);
        *reinterpret_cast<uint64_t*>(p4) = base + PARAM2_3;
        *reinterpret_cast<uint64_t*>(p4 + 0x38) = reinterpret_cast<uint64_t>(p4);

        using CreateFn = void(*)(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);
        using SendFn = void(*)(uint64_t, uint64_t);
        auto createParam2 = reinterpret_cast<CreateFn>(base + CREATE_PARAM2);
        auto sendMessage = reinterpret_cast<SendFn>(base + SEND_MESSAGE);
        const uint64_t global = *reinterpret_cast<uint64_t*>(base + PARAM2_GLOBAL);
        createParam2(reinterpret_cast<uint64_t>(out), reinterpret_cast<uint64_t>(p2),
                     reinterpret_cast<uint64_t>(p3), reinterpret_cast<uint64_t>(p4),
                     reinterpret_cast<uint64_t>(buf), global);
        sendMessage(reinterpret_cast<uint64_t>(s2), reinterpret_cast<uint64_t>(out));
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}
}  // namespace

namespace WeChatAgentVoice {
bool Ready() {
    auto* module = GetModuleHandleW(L"Weixin.dll");
    if (!module) return false;
    const auto base = reinterpret_cast<uintptr_t>(module);
    __try {
        if (base + SEND_MESSAGE < base) return false;
        const auto* code = reinterpret_cast<const unsigned char*>(base + SEND_MESSAGE);
        return code[0] == 0x55 || code[0] == 0x40 || code[0] == 0x48;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

bool Send(const std::string& target, const std::string& silkPath, uint64_t durationMs) {
    if (target.empty() || target.size() > 256 || durationMs == 0 || durationMs > 60000) return false;
    std::ifstream input(std::filesystem::path(silkPath), std::ios::binary);
    if (!input) return false;
    std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(input)), {});
    if (bytes.size() < 16 || bytes.size() > 4 * 1024 * 1024) return false;
    if (bytes[0] != 0x02 && std::memcmp(bytes.data(), "#!SILK_V3", 9) != 0) return false;
    auto* module = GetModuleHandleW(L"Weixin.dll");
    if (!module) return false;
    const std::string guid = GuidString();
    return CallSendRaw(reinterpret_cast<uintptr_t>(module), target.data(), target.size(),
                       bytes.data(), bytes.size(), durationMs, guid.data(), guid.size());
}
}  // namespace WeChatAgentVoice
