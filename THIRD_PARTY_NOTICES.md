# Third-party notices

This repository bundles or builds on the following third-party components.

## silk_v3_encoder.exe

- File: `bin/silk_v3_encoder.exe`
- Source: <https://github.com/kn007/silk-v3-decoder>
- Used to encode 24 kHz mono PCM into SILK v3, compatible with WeChat/QQ (`-tencent`).
- See the upstream repository for its license and notices.

## WeChat-Hook

- Directory: `native/hook-copy/WeChat-Hook`
- Source: <https://github.com/aixed/WeChat-Hook>
- Commit: `e905d07ade50d2c6472e4eb3bd4f3fe19cf662c6`
- Used as the blueprint for the optional `/SendVoiceMsg` native route. The upstream project does not provide a voice-send route; the route in `native/hook-copy/native-hook/voice_sender.cpp` is added by this project.
- See the upstream repository for its license and notices. This repository does not relicense upstream code.

## Python dependencies

Installed by `setup.ps1` from `requirements.txt`:

- [Frida](https://frida.re/) — wxWindows Library Licence
- [NumPy](https://numpy.org/) — BSD-3-Clause
- [psutil](https://github.com/giampaolo/psutil) — BSD-3-Clause
- [SoundCard](https://github.com/bastibe/SoundCard) — BSD-3-Clause

They are not vendored in this repository.
