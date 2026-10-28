# native/ — 可选的原生 hook 副本

这里是一份从 WeChatAgent 复制出来再改的 hook，不碰现有安装。

```text
native/
  hook-copy/
    WeChat-Hook/        上游 aixed/WeChat-Hook 源码副本
    native-hook/        WeChatAgent 定制路由 + voice_sender.cpp/h
  prebuilt/version.dll  预编译改版（4.1.10.27）
  build-voice-hook.ps1  从源码编译
  build-source/         编译临时目录（gitignore）
  build/                编译输出（gitignore）
```

## 新增路由

`POST /SendVoiceMsg`

```json
{
  "wxidorgid": "wxid_xxx",
  "path": "D:\\...\\state\\files\\outgoing\\<64位hex>\\voice.silk",
  "duration": 3400
}
```

要求：

- `Authorization: Bearer <wechatagent-hook.token>`
- `X-WeChatAgent-Account: <数据库账号>`
- 微信 4.1.10.27
- SILK 文件必须在 `state/files/outgoing/<64位hex>/` 下，16 B ~ 4 MB

`/WeChatAgent/health` 会返回 `"nativeVoiceSend": true`。

## 编译

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build-voice-hook.ps1
```

需要 Visual Studio C++ Build Tools + Windows SDK。输出：

```text
native/build/version.dll
```

预编译版校验：

```text
native/prebuilt/version.dll
sha256 = dac3a4f442ba0de16996304e2ab6358de9437ab6ec45c721dfcd96c66207c691
```
