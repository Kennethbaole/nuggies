"""Speech-to-text client for the Qwen ASR service on the Jetson.

The laptop browser records the other person; the app sends that audio here,
and this posts it to ASR_URL (backend.asr_server on the Jetson, reached
directly, over an SSH tunnel or over Tailscale). The transcript then feeds the
reply suggestions as typed text would. Standard library only.
"""

import base64
import json
import os
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .envfile import load_env

DEFAULT_TIMEOUT_S = 10.0
MAX_AUDIO_BYTES = 2_500_000
MAX_TRANSCRIPT_CHARS = 300


class TranscriptionUnavailable(RuntimeError):
    """The ASR service is not configured, unreachable, busy or gave no transcript."""


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    model: str
    latency_ms: int


def default_transport(url, headers, body, timeout):
    data = None if body is None else json.dumps(body).encode()
    request = Request(url, data=data, headers=headers, method="GET" if body is None else "POST")
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(1024 * 1024))


class RemoteTranscriber:
    def __init__(self, transport=None, timeout=None):
        load_env()
        self.url = os.environ.get("ASR_URL", "").rstrip("/")
        self.token = os.environ.get("ASR_TOKEN", "")
        if self.url and urlsplit(self.url).scheme not in ("http", "https"):
            raise ValueError("ASR_URL must start with http:// or https://")
        self.timeout = timeout if timeout is not None else float(os.environ.get("ASR_TIMEOUT_S", DEFAULT_TIMEOUT_S))
        self.transport = transport or default_transport

    @property
    def available(self):
        return bool(self.url)

    def headers(self):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def call(self, path, body):
        if not self.available:
            raise TranscriptionUnavailable("Speech-to-text is not configured (ASR_URL)")
        try:
            return self.transport(self.url + path, self.headers(), body, self.timeout)
        except HTTPError as error:
            # The service's error text is ours, but keep remote bodies out of the UI anyway.
            reason = {401: "rejected the token (ASR_TOKEN)", 429: "is busy", 413: "rejected the audio size"}.get(
                error.code, f"returned HTTP {error.code}")
            raise TranscriptionUnavailable(f"Speech-to-text service {reason}") from error
        except (URLError, TimeoutError, OSError, ValueError) as error:
            raise TranscriptionUnavailable("Speech-to-text service unreachable; is the Jetson tunnel up?") from error

    def health(self):
        data = self.call("/health", None)
        if not isinstance(data, dict):
            raise TranscriptionUnavailable("Speech-to-text service returned an invalid health report")
        return data

    def transcribe(self, audio, mime_type=None):
        if not audio or len(audio) > MAX_AUDIO_BYTES:
            raise ValueError("Audio must be between 1 byte and 2.5 MB")
        body = dict(audio_b64=base64.b64encode(audio).decode(), mime_type=mime_type or "")
        started = time.monotonic()
        data = self.call("/transcribe", body)
        latency = round((time.monotonic() - started) * 1000)
        text = data.get("text") if isinstance(data, dict) else None
        if not isinstance(text, str):
            raise TranscriptionUnavailable("Speech-to-text service returned no transcript")
        language = data.get("language")
        model = data.get("model")
        return Transcript(" ".join(text.split())[:MAX_TRANSCRIPT_CHARS],
                          language if isinstance(language, str) else "",
                          model if isinstance(model, str) else "", latency)
