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
SUPER, installs Ollama and Piper with a model and voice, and installs Qwen3-ASR
speech-to-text with GPU torch in its own `.venv-asr` (`OLLAMA_MODEL`,
`PIPER_VOICE`, `ASR_MODEL` and `TORCH_INDEX_URL` override the defaults). It stops before installing anything on
unsupported hardware, checks each download and build, then runs each tool and
ends with a PASS/FAIL/PENDING summary; any FAIL exits non-zero. PENDING means a
reboot or re-login is needed, then re-run to confirm. It has not been run on a
Jetson yet.

Why Ollama and Piper: both let the Jetson work without the internet or a
cloud account.

- **Ollama** runs a small Qwen model (default `qwen3:1.7b`) on the Jetson. It
  writes every reply suggestion, so they work offline. The curated phrase bank
  stays as the fallback when the model is not running.
- **Piper** is local text-to-speech. It is meant as an offline voice when
  ElevenLabs is unconfigured or unreachable, and to avoid relying on whatever
  browser voices the Jetson happens to have.
- **Qwen3-ASR** turns the other person's speech into text on the Jetson
  (`backend.asr_server`). Ollama's models only read text, so this is what lets
  offline suggestions respond to what was said. It is the only speech-to-text:
  the reply model receives the transcript, never audio, and listening works
  without a reply model (the transcript is shown and the phrases stay). Default `Qwen/Qwen3-ASR-0.6B`;
  `Qwen/Qwen3-ASR-1.7B` is more accurate but tight beside Ollama in 8 GB of
  shared memory. It replaces the earlier whisper.cpp plan.

Ollama and Qwen are wired into the app; Piper is installed only. The Qwen
install path (Jetson torch wheels, then `qwen-asr` from `requirements-asr.txt`)
has not been run on a Jetson yet. If `torch.cuda.is_available()` is false, the
script stops and suggests the `jp6/cu129` index.

## 3. Verify the host-only app

- [ ] Open `http://127.0.0.1:8765` on the Jetson; navigate/select with keyboard.
- [ ] Open `/hud` in another window; confirm the same selected sentence/slot.
- [ ] Enable speech in one companion; test browser voice and text fallback.
- [ ] Run a seeded scenario replay and label it synthetic.
- [ ] Connect the Nano over USB; find its port with `scripts.doctor` and check
  raw counts with `python3 -m backend.app --serial-port <port>`.

## 4. Speech-to-text link (Qwen on the Jetson, mic on the laptop)

The microphone is the laptop's: the companion page records the other person in
the browser, `backend.app` on the laptop posts that audio to `ASR_URL`, and the
Jetson answers with text. The laptop never needs torch or the model.

```
laptop browser mic -> backend.app (laptop) -> ASR_URL --tunnel--> backend.asr_server (Jetson, Qwen)
                                           <- {"text": ...} <-
```

On the Jetson, start the service. It loads and warms the model before opening
the port, so it is ready when the first request arrives:

```sh
.venv-asr/bin/python -m backend.asr_server --self-test some.wav   # one-off check
.venv-asr/bin/python -m backend.asr_server                        # serves 127.0.0.1:8000
```

Pick one way for the laptop to reach it:

- **SSH tunnel** (same network, quickest): keep the service on 127.0.0.1 and
  run `ssh -N -L 8000:127.0.0.1:8000 <user>@<jetson>` on the laptop. Set
  `ASR_URL=http://127.0.0.1:8000`. No token needed; SSH does the auth.
- **Tailscale** (any network): install it on both, then on the Jetson run
  `ASR_TOKEN=<secret> .venv-asr/bin/python -m backend.asr_server --host <jetson-tailscale-ip>`.
  On the laptop set `ASR_URL=http://<jetson-tailscale-ip>:8000` and the same
  `ASR_TOKEN`. The service refuses to bind beyond localhost without a token.

Avoid public tunnels (ngrok, Cloudflare quick tunnels): the service receives
recordings of people talking.

Check from the laptop, in order:

```sh
python -m scripts.try_transcribe --health        # tunnel + service up
python -m scripts.try_transcribe --record 5      # laptop mic -> Jetson -> text
python -m backend.app                            # then use Listen on the companion
```

Listening needs only `ASR_URL`. If Qwen is unreachable, Listen reports the
tunnel and the audio is sent nowhere else; typed text still works.
`POST /api/transcribe` on the app returns the transcript alone, for features
that need text without reply suggestions.

For development, `python -m scripts.dev` runs `backend.app` and, when `ASR_URL`
points at this machine and nothing answers there yet, `backend.asr_server` from
`.venv-asr`, both hidden with their output in one terminal. If a tunnel already
answers on `ASR_URL`, it uses that and starts only the app.

To start the service at boot, a user systemd unit is enough (adjust the path):

```ini
# ~/.config/systemd/user/nuggies-asr.service
[Unit]
Description=Nuggies Qwen speech-to-text

[Service]
WorkingDirectory=%h/nuggies
ExecStart=%h/nuggies/.venv-asr/bin/python -m backend.asr_server
Restart=on-failure

[Install]
WantedBy=default.target
```

Then run `systemctl --user enable --now nuggies-asr` and `sudo loginctl enable-linger $USER`.

- [ ] Record model load time, warm latency for a 5 s clip and memory (`tegrastats`)
  with Ollama loaded at the same time.

## 5. Start the app at boot (headless demos)

A user unit starts the companion at power-on with no monitor or login. It
binds the LAN so phones can connect, which requires `APP_TOKEN` in `.env`.
With `--serial-port` and no `--record`, the app reopens the port every 2 s,
so the Nano can be plugged in after boot or reseated mid-demo. That
reconnect is tested with a mocked port only; unplug/replug has not been
tried on the Jetson.

```ini
# ~/.config/systemd/user/nuggies-app.service
[Unit]
Description=Nuggies companion app
After=network-online.target
StartLimitIntervalSec=0

[Service]
WorkingDirectory=%h/nuggies
ExecStart=%h/nuggies/.venv/bin/python -m backend.app --host :: --serial-port /dev/ttyACM0
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

Run `systemctl --user enable --now nuggies-app` and `sudo loginctl enable-linger $USER`.
Stop any manual `backend.app` first; only one process can hold port 8765 and
the Nano. Logs: `journalctl --user -u nuggies-app -f`.

Phones open `http://<hostname>.local:8765` (avahi mDNS) and enter the token.
`--host ::` listens on IPv4 and IPv6, so a laptop that joins an iPhone
hotspot without getting an IPv4 lease can still use `http://[<jetson-ipv6>]:8765`
(the non-`temporary` address from `ip -6 addr show scope global`).
For rooms whose Wi-Fi blocks device-to-device traffic, plug in Ethernet and
run a hotspot on the Wi-Fi radio that comes up at boot; phones then use
`http://10.42.0.1:8765`:

```sh
sudo nmcli device wifi hotspot ifname <wifi-device> ssid <ssid> password '<8+ chars>'
sudo nmcli connection modify Hotspot connection.autoconnect yes
```
