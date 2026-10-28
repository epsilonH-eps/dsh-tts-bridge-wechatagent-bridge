#pragma once
#include <cstdint>
#include <string>

namespace WeChatAgentVoice {
// 只发已经落盘的 SILK（微信语音格式），target 是 wxid 或群 id。
bool Ready();
bool Send(const std::string& target, const std::string& silkPath, uint64_t durationMs);
}
