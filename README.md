# dsh-tts-bridge-wechatagent-bridge

把 **朗读桥**（`dsh-tts-bridge`）念出来的声音，变成**真正的微信语音条**，发到当前微信聊天。

不是文件卡片，也不是虚拟声卡 + 麦克风按住说话。

## 特性

- 朗读桥在 Edge / `chat.deepseek.com` 页面里念文字；
- WASAPI loopback 录下系统正在播放的声音；
- 如果朗读桥页面没出声，自动用 **edge-tts**（`zh-CN-XiaoxiaoNeural`）兜底，仍然发原生语音条；
- 自动裁静音、转 24 kHz 单声道 PCM、编码成微信 SILK；
- 优先调用改过的 WeChatAgent hook `/SendVoiceMsg`；原版 hook 没有该路由时自动退回 Frida `send_message`；
- 发送后用 WeChatAgent reader 数据库确认新的 `localType=34` 语音消息；
- 作为 DSH 工具 `wechat_voice_send` 暴露给微信里的智能体，它可以自己决定什么时候用语音。

## 链路

```text
WeChatAgent 微信会话
  → DSH 工具 wechat_voice_send(text)
  → 朗读桥 /say
  → Edge chat.deepseek.com 朗读
  → WASAPI loopback 录音
  → 没出声时：edge-tts 兜底
  → 裁剪 + 24k PCM + SILK
  → WeChatAgent hook /SendVoiceMsg   （可选）
     └─ 没有该路由时：Frida send_message
  → 微信原生语音条
  → reader 数据库确认 localType=34
```

## 环境要求

- Windows 10/11 x64
- 匹配版微信 **4.1.10.27**（WeChatAgent 的 hook 版本锁）
- 已安装并登录 DSH / WeChatAgent
- Edge 里的 `https://chat.deepseek.com` 页面开着并登录（优先用朗读桥的声音）；朗读桥不出声时 edge-tts 兜底，需要能访问 Microsoft 语音服务
- Python 3.10+（推荐 3.12）
- 可选：Visual Studio C++ Build Tools（只在你要自己编译 native hook 时需要）

## 安装

### 1. 放到任意目录

例如：

```text
D:\dsh-mod\dsh-tts-bridge-wechatagent-bridge
```

### 2. 建 Python 环境

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

如果 `python` 不在 PATH：

```powershell
.\setup.ps1 -Python "C:\Path\To\python.exe"
```

会生成 `.venv` 并安装 `requirements.txt`。

### 3. 装进 DSH profile

```powershell
dsh plugin --profile desktop add "link:D:\dsh-mod\dsh-tts-bridge-wechatagent-bridge"
```

如果 `dsh.profile.bundles` 里没有 `dsh-tts-bridge-wechatagent-bridge`，手动加在数组末尾：

```json
"dsh-tts-bridge-wechatagent-bridge"
```

然后**完全退出 DSH 再打开**（托盘退出，不是关窗口），让工具重新注册。

### 4. 给微信会话开工具权限

在 `WeChatAgent\data\workspace\config\wechatagent.json` 的目标聊天里，把工具名加进 `dshAccess.chats["wechat:private:<id>"].tools`：

```json
"tools": [
  "...",
  "wechat_voice_send"
]
```

`state/bridge-config.json` 里的 `platforms.wechat.dshAccess` 同步加一份。

### 5. 让智能体知道它可以用

工具描述已经写成“想用声音时就可以主动调用”，不需要用户每次说“发语音”。重启 DSH 后生效。

## 用法

### 智能体调用

微信里正常聊天即可；适合短句、情绪、晚安/安抚/撒娇/提醒时它会自己用语音。也可以明确说：

> 用朗读桥发一条语音，内容是：今天辛苦了，早点休息。

工具参数：

```json
{
  "text": "要念的文字",
  "maxSeconds": 35
}
```

### 命令行

```powershell
$d = "D:\dsh-mod\dsh-tts-bridge-wechatagent-bridge"
& "$d\.venv\Scripts\python.exe" "$d\lib\bridge.py" `
  --text "你好，这是朗读桥发来的语音。" `
  --chat "wechat:private:128560812" `
  --wechat-root "D:\WeChatAgent\data\workspace" `
  --mode auto
```

`--mode`：

- `auto`：有 `/SendVoiceMsg` 就先走 hook，否则 Frida；
- `hook`：强制 hook，路由不存在就报错；
- `frida`：强制 Frida。

成功返回：

```json
{
  "ok": true,
  "engine": "WeChatAgent hook /SendVoiceMsg",
  "confirmed": true,
  "messageId": "51",
  "durationMs": 2400
}
```

## 可选：把语音路由加进 hook 副本

仓库里的 `native/` 是一份**复制出来再改**的 hook，不碰现有 WeChatAgent 的 `state\hook`。

```text
native/
  hook-copy/
    WeChat-Hook/        上游源码副本
    native-hook/        WeChatAgent 定制路由 + voice_sender.cpp/h
  prebuilt/version.dll  预编译的改版 hook（4.1.10.27）
  build-voice-hook.ps1  从源码重新编译
```

预编译版：

```text
native/prebuilt/version.dll
sha256 = dac3a4f442ba0de16996304e2ab6358de9437ab6ec45c721dfcd96c66207c691
```

它有：

- 原有文本、文件、表情路由；
- 新增 `POST /SendVoiceMsg`；
- `/WeChatAgent/health` 多一个 `"nativeVoiceSend": true`。

### 安装改版 hook（可选）

只在匹配版 **4.1.10.27** 客户端上做，先备份：

```powershell
$dir = "D:\WeChatAgent\data\workspace\state\hook\wechat-4.1.10.27"
Copy-Item "$dir\version.dll" "$dir\version.dll.original" -Force
Copy-Item ".\native\prebuilt\version.dll" "$dir\version.dll" -Force
Start-Process "$dir\Weixin.exe" -ArgumentList "StartPort=30001" -WorkingDirectory $dir
```

验证：

```powershell
$token = (Get-Content "$dir\wechatagent-hook.token" -Raw).Trim()
Invoke-RestMethod "http://127.0.0.1:30001/WeChatAgent/health" `
  -Headers @{ Authorization = "Bearer $token" }
```

看到 `nativeVoiceSend: true` 即生效。

> WeChatAgent 的 `launch-hook-wechat.ps1` 会用 `state\hook\native\version.dll` 和 `build.json` 做哈希校验。要把改版 hook 纳入它的启动流程，需要同时替换这两个文件并更新 `build.json` 的 `sha256`/`voiceRoute`。

### 自己编译

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\native\build-voice-hook.ps1
```

需要 MSVC + Windows SDK；默认用 `vswhere` 找 MSBuild，也可传 `-MsBuild <path>`。

## 配置

- `WECHATAGENT_ROOT`：WeChatAgent 数据目录，默认 `D:\WeChatAgent\data\workspace`；
- `--chat`：`wechat:private:<id>` 或 `wechat:group:<id>`；
- 语音编码器：`bin/silk_v3_encoder.exe`（SILK v3，`-tencent`）。

## 安全与边界

- 优先用朗读桥；页面没开、没登录或点了朗读不出声时自动 edge-tts 兜底，两者都失败才报错；
- edge-tts 兜底需要网络；声音是 `zh-CN-XiaoxiaoNeural`，不是 DeepSeek 网页端的声音；
- 单条语音建议 1~200 字，工具层限制 500 字；
- 依赖 Weixin.dll **4.1.10.27** 的偏移（`send_message`、语音 vtable、参数构造）；微信升级后需要重新核对；
- Frida 会注入微信进程；只建议在本机使用；
- 改版 hook 会替换客户端 `version.dll`，务必先备份；
- 不要把 `wechatagent-hook.token`、账号数据、聊天记录提交进仓库。

## 常见问题

**Q：DSH 里没有 `wechat_voice_send`？**

检查：

1. `desktop` profile 的 `dsh.profile.bundles` 是否有本包；
2. 是否完全退出并重开 DSH；
3. `WeChatAgent` 的 `dshAccess` 是否加了工具名。

**Q：报 schema `type: null`？**

本仓库的 `lib/index.js` 已使用完整 JSON Schema（`type: "object"` + `required`），不会再走简化参数表。

**Q：`/SendVoiceMsg` 返回 409？**

通常是微信没登录、账号不唯一，或 `nativeVoiceSend` 不为 true。

**Q：返回“当前微信进程没有 /SendVoiceMsg 路由”？**

说明加载的还是原版 hook：确认替换后重启了微信，并且 `health.nativeVoiceSend` 为 `true`。

**Q：WeChatAgent 启动时报 `Native build hash/version mismatch`？**

`state\hook\native\version.dll` 与 `build.json.sha256` 不一致。恢复原版 DLL/原 `build.json`，或把两者一起更新为改版并同步 `sha256`。

## 目录

```text
lib/
  index.js          DSH 工具注册
  bridge.py         朗读桥录音、SILK、目标解析、发送、回执
  send_voice.py     Frida 原生语音发送（fallback）
bin/
  silk_v3_encoder.exe
native/
  hook-copy/        hook 源码副本
  prebuilt/         改版 version.dll + sha256
  build-voice-hook.ps1
cordis.patch.yml
package.json
requirements.txt
setup.ps1
```

## 许可

本项目代码 MIT。第三方组件见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
