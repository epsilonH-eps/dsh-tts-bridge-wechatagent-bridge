"""Call Weixin's own send_message with a constructed voice-message object.

This is the native half of the bridge.  It does not use or modify the
WeChatAgent version.dll hook: it attaches with Frida, builds the same kind of
message object WeChat itself builds for a voice bubble, and calls the send
function once.
"""

from __future__ import annotations

import json
import time
from typing import Any

import frida


JS_TEMPLATE = r"""
const base = Process.getModuleByName('Weixin.dll').base;
const k32 = Process.getModuleByName('kernel32.dll');
const GetProcessHeap = new NativeFunction(k32.getExportByName('GetProcessHeap'), 'pointer', []);
const HeapAlloc = new NativeFunction(k32.getExportByName('HeapAlloc'), 'pointer', ['pointer', 'uint32', 'size_t']);
const heap = GetProcessHeap();
const silk = new Uint8Array(SILK_BYTES);
const wxid = WXID_JSON;
const duration = DURATION_MS;

function alloc(n) {
  const p = HeapAlloc(heap, 0, n);
  if (p.isNull()) throw new Error('HeapAlloc failed ' + n);
  return p;
}
function setStr(addr, s) {
  const bytes = [];
  for (let i = 0; i < s.length; i++) bytes.push(s.charCodeAt(i) & 0xff);
  addr.writeByteArray(new Uint8Array(16));
  if (bytes.length < 16) {
    addr.writeByteArray(bytes);
  } else {
    const p = alloc(bytes.length + 1);
    p.writeByteArray(bytes);
    addr.writePointer(p);
  }
  addr.add(0x10).writeU64(bytes.length);
  addr.add(0x18).writeU64(bytes.length < 16 ? 0xF : bytes.length + 12);
}

try {
  const msg = alloc(0x800);
  msg.writeByteArray(new Uint8Array(0x800));
  msg.writePointer(base.add(0x8DCFF98));
  msg.add(8).writeU64(0x0000000200000001);
  msg.add(0x10).writePointer(base.add(0x8DD0028));
  msg.add(0x18).writePointer(msg.add(0x10));
  msg.add(0x20).writePointer(msg);
  for (const off of [0x40, 0x60, 0x80, 0xA0, 0x130, 0x170, 0x190, 0x1B8, 0x668, 0x688, 0x6B0, 0x6F0, 0x710, 0x770]) {
    msg.add(off).writeU64(0xF);
  }
  msg.add(0xA8).writeU64(0x0000000100000000);
  msg.add(0xB0).writeU64(0x0000000700000000);
  setStr(msg.add(0xC0), wxid);
  msg.add(0x108).writeU64(7);
  msg.add(0x150).writeU64(7);
  msg.add(0xE8).writeU64(34);
  const guid = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
  });
  setStr(msg.add(0x6B8), guid);
  const silkPtr = alloc(silk.length + 64);
  silkPtr.writeByteArray(silk);
  msg.add(0x718).writePointer(silkPtr);
  msg.add(0x728).writeU64(silk.length);
  msg.add(0x730).writeU64(silk.length + 16);
  msg.add(0x738).writeU64(duration);
  msg.add(0x740).writeU64(0x0000000300000004);
  msg.add(0x748).writeU64(30000);

  const s1 = alloc(0x20);
  s1.writePointer(msg.add(0x10));
  s1.add(8).writePointer(msg);
  s1.add(0x10).writePointer(ptr(0));
  s1.add(0x18).writeU64(0);

  const s2 = alloc(0x28);
  s2.writePointer(base.add(0x84EC9C8));
  s2.add(8).writePointer(s1);
  s2.add(0x10).writePointer(s1.add(0x10));
  s2.add(0x18).writePointer(s1.add(0x10));
  s2.add(0x20).writeU64(1);

  const out = alloc(0xE8);
  out.writeByteArray(new Uint8Array(0xE8));
  const p2 = alloc(0x40); p2.writeByteArray(new Uint8Array(0x40));
  const p3 = alloc(0x40); p3.writeByteArray(new Uint8Array(0x40));
  const p4 = alloc(0x40); p4.writeByteArray(new Uint8Array(0x40));
  p2.writePointer(base.add(0x8595F58)); p2.add(0x38).writePointer(p2);
  p3.writePointer(base.add(0x8595E98)); p3.add(0x38).writePointer(p3);
  p4.writePointer(base.add(0x8595DD8)); p4.add(0x38).writePointer(p4);
  const buf = alloc(0x80); buf.writeByteArray(new Uint8Array(0x80));

  const createParam2 = new NativeFunction(base.add(0xDF40), 'void', ['pointer','pointer','pointer','pointer','pointer','pointer']);
  const globalValue = base.add(0xA0CE0B0).readPointer();
  createParam2(out, p2, p3, p4, buf, globalValue);
  const sendMessage = new NativeFunction(base.add(0x1677A30), 'void', ['pointer','pointer']);
  sendMessage(s2, out);
  send({ ok: true, msg: msg.toString(), silk: silkPtr.toString(), len: silk.length, duration: duration });
} catch (e) {
  send({ ok: false, error: String(e), stack: e && e.stack ? String(e.stack) : '' });
}
"""


def send_voice(pid: int, silk: bytes, wxid: str, duration_ms: int, timeout: float = 10.0) -> dict[str, Any]:
    js = (
        JS_TEMPLATE.replace("SILK_BYTES", json.dumps(list(silk)))
        .replace("WXID_JSON", json.dumps(wxid))
        .replace("DURATION_MS", str(duration_ms))
    )
    session = frida.attach(pid)
    result: dict[str, Any] | None = None

    def on_message(message, data):
        nonlocal result
        if message.get("type") == "send":
            result = message.get("payload")
        elif message.get("type") == "error":
            result = {"ok": False, "error": message.get("description") or str(message)}

    script = session.create_script(js)
    script.on("message", on_message)
    script.load()
    deadline = time.time() + timeout
    while time.time() < deadline and result is None:
        time.sleep(0.05)
    try:
        script.unload()
    except Exception:
        pass
    try:
        session.detach()
    except Exception:
        pass
    if result is None:
        return {"ok": False, "error": "frida_send_timeout"}
    return result
