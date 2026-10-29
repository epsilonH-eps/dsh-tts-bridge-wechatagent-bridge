"""朗读桥 -> 微信语音条 的桥接器。

流程：
  1. 让 dsh-tts-bridge 在 Edge/DeepSeek 页面里念一段文字；
  2. 用 WASAPI loopback 录下系统正在播放的声音；
  3. 裁剪静音、转成 24k 单声道 PCM，再用 SILK 编码器压成微信语音；
  4. 用 Frida 在微信进程里构造一条原生语音消息并发送。

这个脚本不依赖、也不修改 WeChatAgent 的 version.dll Hook。
"""

from __future__ import annotations

import argparse
import audioop
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import wave
from pathlib import Path
from typing import Any

import numpy as np
import psutil
import soundcard as sc

from send_voice import send_voice

RATE = 48000
CHANNELS = 2
PACKET = RATE // 10  # 100 ms
BRIDGE_WHERE = "http://127.0.0.1:19387/dsh-tts-bridge/where"


def http_json(url: str, payload: dict | None = None, timeout: float = 10.0, headers: dict | None = None) -> Any:
    data = None
    hdrs = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def bridge_base() -> str:
    try:
        info = http_json(BRIDGE_WHERE, timeout=3)
        base = str(info.get("base") or "").rstrip("/")
        if base.startswith("http://127.0.0.1:"):
            return base
    except Exception:
        pass
    raise RuntimeError("找不到朗读桥：先确认 DSH 的朗读桥插件已加载、19387 端口在监听")


def wechat_pid() -> int:
    candidates = []
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "create_time"]):
        try:
            info = proc.info
            if (info.get("name") or "").lower() != "weixin.exe":
                continue
            exe = info.get("exe") or ""
            cmd = " ".join(info.get("cmdline") or [])
            if "--type=" in cmd or "crashpad" in cmd:
                continue
            if "WeChatAgent" not in exe and "wechat-4.1.10.27" not in exe:
                continue
            candidates.append((info.get("create_time") or 0, info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not candidates:
        raise RuntimeError("没找到正在运行的匹配版微信（Weixin.exe）")
    return max(candidates)[1]


def _rms(chunk: np.ndarray) -> float:
    if chunk.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.asarray(chunk, dtype=np.float64) ** 2)))


def record_bridge_speech(text: str, max_seconds: float) -> tuple[np.ndarray, float]:
    mic = sc.all_microphones(include_loopback=True)[0]
    base = bridge_base()
    chunks: list[np.ndarray] = []
    said: dict[str, Any] = {}
    stop = False

    def trigger() -> None:
        time.sleep(0.6)
        try:
            said.update(http_json(base + "/say", {"text": text}, timeout=10))
        except Exception as exc:  # noqa: BLE001
            said["error"] = str(exc)

    thread = threading.Thread(target=trigger, daemon=True)
    started = time.time()
    start_ms = int(started * 1000)
    thread.start()

    noise: list[float] = []
    speech_started = False
    last_voice = 0.0
    with mic.recorder(samplerate=RATE, channels=CHANNELS) as recorder:
        while not stop:
            chunk = recorder.record(numframes=PACKET)
            chunks.append(np.asarray(chunk, dtype=np.float32))
            now = time.time()
            level = _rms(chunk)
            if not speech_started and now - started < 0.8:
                noise.append(level)
            threshold = max(0.0018, (max(noise) if noise else 0.0) * 4.0)
            if level > threshold:
                speech_started = True
                last_voice = now
            elif speech_started and now - last_voice > 1.2:
                stop = True
            if now - started > max_seconds:
                stop = True
            if said.get("error"):
                break

    if said.get("error"):
        raise RuntimeError("朗读桥没有接收这次朗读：" + str(said["error"]))
    try:
        state = http_json(base + "/state", timeout=3)
        recent = [h for h in (state.get("history") or []) if int(h.get("at") or 0) >= start_ms - 500]
        if recent and recent[0].get("ok") is False:
            raise RuntimeError("朗读桥页面没有出声：" + str(recent[0].get("error") or "点了朗读但没出声"))
        if not state.get("playing") and int(state.get("waiting") or 0) > 0 and not recent:
            raise RuntimeError("朗读桥还没有接走这次朗读（扩展没在取件）")
    except RuntimeError:
        raise
    except Exception:
        pass
    if not chunks:
        raise RuntimeError("没有录到任何音频")
    audio = np.concatenate(chunks, axis=0)
    mono = audio.mean(axis=1)
    step = PACKET
    levels = np.array([_rms(mono[i:i + step]) for i in range(0, len(mono) - step, step)])
    peak = float(np.max(levels)) if levels.size else 0.0
    threshold = max(0.0018, peak * 0.12)
    hits = np.where(levels > threshold)[0]
    if not hits.size:
        raise RuntimeError("朗读桥页面没有出声：确认 Edge 里的 chat.deepseek.com 开着且已登录")
    start = max(0, int(hits[0] * step) - int(RATE * 0.20))
    end = min(len(mono), int((hits[-1] + 1) * step) + int(RATE * 0.30))
    clip = mono[start:end]
    if len(clip) < RATE * 0.35:
        raise RuntimeError("录到的语音太短，可能是朗读桥还没开始念")
    return clip, float(len(clip)) / RATE


def edge_tts_speak(text: str, work: Path) -> tuple[np.ndarray, float]:
    """朗读桥没出声时的兜底：用 edge-tts 生成同一段话的语音。"""
    import asyncio
    import edge_tts
    import miniaudio

    mp3 = work / "fallback.mp3"
    asyncio.run(edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural").save(str(mp3)))
    decoded = miniaudio.decode_file(
        str(mp3),
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=RATE,
    )
    pcm = np.frombuffer(decoded.samples.tobytes(), dtype=np.int16)
    if pcm.size == 0:
        raise RuntimeError("edge-tts 兜底生成失败")
    clip = pcm.astype(np.float32) / 32768.0
    return clip, float(len(clip)) / RATE


def encode_silk(clip: np.ndarray, work: Path, duration: float) -> tuple[Path, int]:
    pcm16 = (np.clip(clip, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
    if RATE != 24000:
        pcm16, _ = audioop.ratecv(pcm16, 2, 1, RATE, 24000, None)
    wav_path = work / "voice.wav"
    with wave.open(str(wav_path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(24000)
        fh.writeframes(pcm16)
    pcm_path = work / "voice.pcm"
    pcm_path.write_bytes(pcm16)
    silk_path = work / "voice.silk"
    encoder = Path(__file__).resolve().parent.parent / "bin" / "silk_v3_encoder.exe"
    if not encoder.exists():
        raise RuntimeError("缺少 SILK 编码器：" + str(encoder))
    proc = subprocess.run(
        [str(encoder), str(pcm_path), str(silk_path), "-Fs_API", "24000", "-tencent"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0 or not silk_path.exists():
        raise RuntimeError("SILK 编码失败：" + (proc.stderr or proc.stdout)[-400:])
    return silk_path, int(round(duration * 1000))


def onebot_id(value: str) -> int:
    import hashlib

    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 2147483647 + 1


def resolve_wxid(root: Path, chat: str) -> tuple[str, str, str]:
    io = json.loads((root / "state" / "wechat-io-config.json").read_text(encoding="utf-8"))
    base = io["reader_base_url"].rstrip("/")
    token = io["reader_token"]
    req = urllib.request.Request(base + "/api/v1/sessions?limit=500", headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    parts = chat.split(":")
    if len(parts) != 3 or parts[0] != "wechat":
        raise RuntimeError("聊天标识格式不对：" + chat)
    kind, target = parts[1], parts[2]
    matches = []
    for session in data.get("sessions") or []:
        username = str(session.get("username") or "")
        if not username:
            continue
        is_group = "@chatroom" in username
        if (kind == "group") != is_group:
            continue
        mapped = session.get("conversationId")
        if mapped is not None:
            if str(mapped) == str(target):
                matches.append(session)
        elif str(onebot_id(username)) == str(target):
            matches.append(session)
    if len(matches) != 1:
        raise RuntimeError(f"找不到唯一的目标聊天：{chat}（匹配到 {len(matches)} 个）")
    return str(matches[0]["username"]), kind, target


def latest_voice(root: Path, wxid: str) -> dict | None:
    io = json.loads((root / "state" / "wechat-io-config.json").read_text(encoding="utf-8"))
    base = io["reader_base_url"].rstrip("/")
    token = io["reader_token"]
    url = base + "/api/v1/messages?talker=" + urllib.parse.quote(wxid) + "&limit=5"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    for row in data.get("messages") or []:
        if row.get("isSend") and row.get("localType") == 34:
            return row
    return None


def try_hook_send(root: Path, wxid: str, silk: bytes, duration_ms: int) -> dict | None:
    """优先走改过的 WeChatAgent hook 的 /SendVoiceMsg；原版 hook 没有这个路由时返回 None。"""
    token_file = root / "state" / "hook" / "native-token.txt"
    if not token_file.exists():
        return None
    token = token_file.read_text(encoding="utf-8").strip()
    try:
        health = http_json(
            "http://127.0.0.1:30001/WeChatAgent/health",
            timeout=3,
            headers={"Authorization": "Bearer " + token},
        )
    except Exception:
        return None
    if not health.get("nativeVoiceSend"):
        return None
    accounts = health.get("databaseAccounts") or []
    if len(accounts) != 1:
        return None
    stage = root / "state" / "files" / "outgoing" / (uuid.uuid4().hex + uuid.uuid4().hex)
    stage.mkdir(parents=True, exist_ok=True)
    target = stage / "voice.silk"
    try:
        target.write_bytes(silk)
        result = http_json(
            "http://127.0.0.1:30001/SendVoiceMsg",
            {"wxidorgid": wxid, "path": str(target), "duration": duration_ms},
            timeout=15,
            headers={
                "Authorization": "Bearer " + token,
                "X-WeChatAgent-Account": accounts[0],
            },
        )
        if result.get("ret") == 0:
            return {"engine": "WeChatAgent hook /SendVoiceMsg", "response": result}
        return None
    except Exception:
        return None
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--chat", required=True)
    parser.add_argument("--wechat-root", required=True)
    parser.add_argument("--max-seconds", type=float, default=35.0)
    parser.add_argument("--mode", choices=["auto", "hook", "frida"], default="auto",
                        help="auto = 有 /SendVoiceMsg 就先用 hook，否则 Frida")
    args = parser.parse_args()

    root = Path(args.wechat_root).resolve()
    work = Path(tempfile.mkdtemp(prefix="dsh-wechat-voice-"))
    t0 = time.time()
    try:
        wxid, kind, target = resolve_wxid(root, args.chat)
        source = "dsh-tts-bridge"
        bridge_error = None
        try:
            clip, duration = record_bridge_speech(args.text, max(12.0, min(args.max_seconds, 60.0)))
        except Exception as exc:  # noqa: BLE001
            bridge_error = str(exc)
            clip, duration = edge_tts_speak(args.text, work)
            source = "edge-tts fallback"
        silk_path, duration_ms = encode_silk(clip, work, duration)
        silk = silk_path.read_bytes()
        if len(silk) > 4 * 1024 * 1024:
            raise RuntimeError("生成的语音太大，已超过微信单条语音的安全范围")
        hook_result = None
        if args.mode in ("auto", "hook"):
            hook_result = try_hook_send(root, wxid, silk, duration_ms)
        if hook_result is not None:
            engine = hook_result["engine"]
        elif args.mode == "hook":
            raise RuntimeError("当前微信进程没有 /SendVoiceMsg 路由：确认替换的是改过的 version.dll 并重启了微信")
        else:
            pid = wechat_pid()
            sent = send_voice(pid, silk, wxid, duration_ms)
            if not sent.get("ok"):
                raise RuntimeError("微信原生发送失败：" + str(sent.get("error") or sent))
            engine = "Frida send_message"
        deadline = time.time() + 8
        receipt = None
        while time.time() < deadline:
            row = latest_voice(root, wxid)
            if row and float(row.get("createTime") or 0) >= t0 - 2:
                receipt = row
                break
            time.sleep(0.4)
        result = {
            "ok": True,
            "engine": source + " + " + engine,
            "chat": args.chat,
            "durationMs": duration_ms,
            "silkBytes": len(silk),
            "confirmed": bool(receipt),
            "messageId": str(receipt.get("localId")) if receipt else None,
            "note": "已提交；confirmed=true 表示数据库已出现新的语音消息。",
        }
        if bridge_error:
            result["bridgeError"] = bridge_error
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
