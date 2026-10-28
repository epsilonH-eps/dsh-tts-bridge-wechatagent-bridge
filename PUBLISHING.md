# 上传到 GitHub

这个目录已经是干净的仓库结构，`.venv`、构建缓存、测试客户端、研究资料都不在里面。

## 方式一：网页上传

1. GitHub 新建仓库（不要勾选自动生成 README，避免冲突）；
2. 解压 `dsh-tts-bridge-wechatagent-bridge-0.1.0.zip`；
3. 把里面的 `dsh-tts-bridge-wechatagent-bridge` 文件夹内容拖进 GitHub 上传页；
4. Commit。

## 方式二：Git 命令

```powershell
cd D:\dsh-mod\github-ready\dsh-tts-bridge-wechatagent-bridge
git init
git add .
git commit -m "feat: 朗读桥到微信语音条"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

## 上传前检查

- 不要提交 `.venv/`、`native/build-source/`、`native/test-client/`、`native/backup/`、`research/`；
- 不要提交 `wechatagent-hook.token`、账号数据库、聊天记录；
- `native/prebuilt/version.dll` 是预编译 hook，保留它的 `SHA256.txt`；
- 第三方来源见 `THIRD_PARTY_NOTICES.md`。
