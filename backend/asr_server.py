"""Qwen3-ASR speech-to-text service. Runs on the Jetson, next to the model.

    .venv-asr/bin/python -m backend.asr_server                     # 127.0.0.1:8000
    .venv-asr/bin/python -m backend.asr_server --self-test clip.wav
    ASR_TOKEN=... .venv-asr/bin/python -m backend.asr_server --host 0.0.0.0

    GET  /health      -> {"ok", "model", "device", "busy"}
    POST /transcribe  {"audio_b64", "mime_type"} -> {"text", "language", "model", "audio_ms", "latency_ms"}

The companion app reaches it through ASR_URL (backend/transcribe.py). Any audio
ffmpeg can read is accepted (the browser sends WebM/Opus); it is converted to
16 kHz mono before Qwen hears it. The model loads and warms up before the port
opens, so the first real request is not slow. Needs ffmpeg plus the .venv-asr
that scripts/setup_jetson.sh creates (Jetson torch + qwen-asr). Audio and
transcripts are never logged or written to disk.
"""

import argparse
import base64
import binascii
import json
import os
import secrets
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .envfile import load_env

DEFAULT_MODEL = "Qwen/Qwen3-ASR-0.6B"  # 1.7B is more accurate but tight beside Ollama in 8 GB.
SAMPLE_RATE = 16000
MAX_BODY = 4 * 1024 * 1024
MAX_AUDIO_S = 30
LOOPBACK = ("127.0.0.1", "localhost", "::1")


def decode_audio(data, ffmpeg="ffmpeg"):
    """Any container/codec ffmpeg understands -> 16 kHz mono signed 16-bit PCM."""
    try:
        result = subprocess.run(
            [ffmpeg, "-nostdin", "-loglevel", "error", "-i", "pipe:0", "-t", str(MAX_AUDIO_S),
             "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"],
            input=data, capture_output=True, timeout=30, check=False)
    except FileNotFoundError as error:
        raise RuntimeError("ffmpeg is not installed") from error
    except subprocess.TimeoutExpired as error:
        raise ValueError("Audio took too long to decode") from error
    if result.returncode != 0 or not result.stdout:
        raise ValueError("Audio could not be decoded")
    return result.stdout


def check_language(language, supported):
    """Empty means auto-detect. Otherwise normalize like qwen-asr ('english' -> 'English')
    and fail fast on names Qwen does not support."""
    language = (language or "").strip()
    if not language:
        return None
    name = language[:1].upper() + language[1:].lower()
    if name not in supported:
        raise RuntimeError(f"Unsupported ASR_LANGUAGE {language!r}; leave it empty to auto-detect, "
                           f"or use one of: {', '.join(supported)}")
    return name


class QwenEngine:
    """Qwen3-ASR through the qwen-asr package (Transformers backend, no vLLM)."""

    def __init__(self, model_id=DEFAULT_MODEL, device="cuda:0", language=None):
        import torch
        from qwen_asr import Qwen3ASRModel
        from qwen_asr.inference.utils import SUPPORTED_LANGUAGES

        # Checked before the slow model load: Qwen would otherwise reject every request.
        language = check_language(language, SUPPORTED_LANGUAGES)
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available to torch; install the Jetson torch wheel (scripts/setup_jetson.sh) or pass --device cpu")
        self.model_id, self.device, self.language = model_id, device, language
        dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32
        self.model = Qwen3ASRModel.from_pretrained(model_id, dtype=dtype, device_map=device)

    def transcribe(self, pcm):
        import numpy as np

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        result = self.model.transcribe(audio=(audio, SAMPLE_RATE), language=self.language)[0]
        return (result.text or "").strip(), getattr(result, "language", "") or ""


class Service:
    def __init__(self, engine, token="", decode=decode_audio):
        self.engine, self.token, self.decode = engine, token, decode
        self.lock = threading.Lock()

    def health(self):
        return dict(ok=True, model=self.engine.model_id, device=self.engine.device, busy=self.lock.locked())

    def transcribe(self, audio):
        """Raises ValueError for bad audio and BlockingIOError when a request is running."""
        if not self.lock.acquire(blocking=False):
            raise BlockingIOError("A transcription is already running")
        try:
            started = time.monotonic()
            pcm = self.decode(audio)
            text, language = self.engine.transcribe(pcm)
            return dict(text=text, language=language, model=self.engine.model_id,
                        audio_ms=round(len(pcm) / 2 / SAMPLE_RATE * 1000),
                        latency_ms=round((time.monotonic() - started) * 1000))
        finally:
            self.lock.release()


def make_handler(service):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Never log tokens or what people said.

        def reply(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def authorized(self):
            if not service.token:
                return True
            return secrets.compare_digest(self.headers.get("Authorization", ""), f"Bearer {service.token}")

        def do_GET(self):
            if not self.authorized():
                return self.reply(401, dict(error="Missing or wrong ASR token"))
            if urlsplit(self.path).path == "/health":
                return self.reply(200, service.health())
            return self.reply(404, dict(error="Unknown endpoint"))

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 < length <= MAX_BODY:
                return self.reply(413, dict(error=f"Request must contain at most {MAX_BODY} bytes"))
            # Read the body before any reply so the client is not reset mid-upload.
            body = self.rfile.read(length)
            if not self.authorized():
                return self.reply(401, dict(error="Missing or wrong ASR token"))
            if urlsplit(self.path).path != "/transcribe":
                return self.reply(404, dict(error="Unknown endpoint"))
            try:
                payload = json.loads(body)
                audio_b64 = payload.get("audio_b64") if isinstance(payload, dict) else None
                if not isinstance(audio_b64, str):
                    raise ValueError("audio_b64 is required")
                try:
                    audio = base64.b64decode(audio_b64, validate=True)
                except binascii.Error as error:
                    raise ValueError("audio_b64 is not valid base64") from error
                if not audio:
                    raise ValueError("audio_b64 is empty")
                return self.reply(200, service.transcribe(audio))
            except BlockingIOError as error:
                return self.reply(429, dict(error=str(error)))
            except ValueError as error:  # Includes malformed JSON.
                return self.reply(400, dict(error=str(error)))
            except Exception as error:  # Keep the service up; report the type only.
                return self.reply(500, dict(error=f"Transcription failed ({type(error).__name__})"))
    return Handler


def main():
    load_env()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=os.environ.get("ASR_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ASR_PORT", "8000")))
    parser.add_argument("--model", default=os.environ.get("ASR_MODEL", DEFAULT_MODEL))
    parser.add_argument("--device", default=os.environ.get("ASR_DEVICE", "cuda:0"), help="cuda:0 on the Jetson; cpu works but is slow")
    parser.add_argument("--language", default=os.environ.get("ASR_LANGUAGE") or None,
                        help="Force a language (e.g. English); default auto-detects")
    parser.add_argument("--self-test", metavar="AUDIO", help="Transcribe one file, print JSON and exit")
    args = parser.parse_args()
    token = os.environ.get("ASR_TOKEN", "")
    if not args.self_test and args.host not in LOOPBACK and not token:
        parser.error("Set ASR_TOKEN before binding beyond localhost (or keep 127.0.0.1 and use an SSH tunnel)")
    if not shutil.which("ffmpeg"):
        parser.error("ffmpeg is not on PATH (Linux: sudo apt-get install ffmpeg; Windows: "
                     "winget install Gyan.FFmpeg, then open a new terminal)")

    print(f"Loading {args.model} on {args.device}...", flush=True)
    started = time.monotonic()
    try:
        engine = QwenEngine(args.model, args.device, args.language)
    except ImportError as error:
        raise SystemExit(f"Missing ASR dependency ({error.name}); run scripts/setup_jetson.sh or use .venv-asr/bin/python") from error
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
    service = Service(engine, token)
    print(f"Loaded in {time.monotonic() - started:.1f} s", flush=True)

    if args.self_test:
        try:
            print(json.dumps(service.transcribe(Path(args.self_test).read_bytes())), flush=True)
        except (ValueError, OSError, RuntimeError) as error:
            raise SystemExit(str(error)) from error
        return

    # Warm-up: the first inference compiles kernels and is much slower than the rest.
    engine.transcribe(b"\x00\x00" * SAMPLE_RATE)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    print(f"Qwen ASR ready: http://{args.host}:{args.port}/transcribe", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
