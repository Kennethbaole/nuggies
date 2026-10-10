# Jetson host handoff

Proposed path: run the existing Python service on the Jetson host and let
browsers/display adapters consume its state. No Jetson was available for
testing. Desktop tests are not ARM/device validation.

## 1. Provision and inventory

The planned board is the **Jetson Orin Nano Super Developer Kit**, not the
older Jetson Nano. Follow NVIDIA's
[official Orin Nano setup](https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/latest/quick_start.html)
for firmware, storage and JetPack before installing anything from this repo.

- [ ] Record module, carrier, OS, architecture, Python and JetPack versions.
- [ ] Check display and audible audio independently before blaming app code.
- [ ] Confirm Python 3.10+ is available.

## 2. Install the app

Do not embed GitHub credentials in shell history.

```sh
git clone https://github.com/Kennethbaole/nuggies.git
cd nuggies
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m scripts.doctor
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m backend.app
```

`scripts/setup_jetson.sh` is the code for the Jetson's first-time setup. Run it
once after NVIDIA provisioning and cloning; it does the steps above and more:
installs packages, the venv and requirements, adds the dialout group, sets MAXN
SUPER, installs Ollama and Piper with a model and voice, and builds whisper.cpp
for the GPU with a speech-to-text model (`OLLAMA_MODEL`, `PIPER_VOICE` and
`WHISPER_MODEL` override the defaults). It stops before installing anything on
unsupported hardware, checks each download and build, then runs each tool and
ends with a PASS/FAIL/PENDING summary; any FAIL exits non-zero. PENDING means a
reboot or re-login is needed, then re-run to confirm. It has not been run on a
Jetson yet.

Why Ollama and Piper: both let the Jetson work without the internet or a
cloud account.

- **Ollama** runs a small Qwen model (default `qwen3:1.7b`) on the Jetson. It
  writes the AI reply suggestions from typed text; set `OLLAMA_MODEL` in `.env`
  to enable them. The curated phrase bank stays as the fallback.
- **Piper** is local text-to-speech. It is meant as an offline voice when
  ElevenLabs is unconfigured or unreachable, and to avoid relying on whatever
  browser voices the Jetson happens to have.
- **whisper.cpp** turns the other person's speech into text on the Jetson.
  Ollama's models only read text, so this is what lets offline suggestions
  respond to what was said. Default model `small.en` (~470 MB); `base.en` is
  faster but less accurate.

Piper and whisper.cpp are not wired into the app yet; the script only installs
them so that integration can be built and measured on the device.

## 3. Verify the host-only app

- [ ] Open `http://127.0.0.1:8765` on the Jetson; navigate/select with keyboard.
- [ ] Open `/hud` in another window; confirm the same selected sentence/slot.
- [ ] Enable speech in one companion; test browser voice and text fallback.
- [ ] Run a seeded scenario replay and label it synthetic.
- [ ] Connect the Nano over USB; find its port with `scripts.doctor` and check
  raw counts with `python3 -m backend.app --serial-port <port>`.
