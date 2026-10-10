"""Server-side ElevenLabs TTS with a voice/settings-specific local audio cache."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .envfile import load_env


class SpeechUnavailable(RuntimeError):
    pass


class ElevenLabsSpeech:
    def __init__(self, cache_dir=None):
        load_env()  # local .env fills variables the shell has not set
        self.api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        self.voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "")
        self.model_id = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
        self.cache_dir = Path(cache_dir or os.environ.get("SPEECH_CACHE_DIR", ".cache/tts"))
        self.settings = dict(stability=0.5, similarity_boost=0.75, style=0.0,
                             use_speaker_boost=True, speed=1.0)
        self.requires_verification = False
        profile = os.environ.get("VOICE_PROFILE_PATH")
        if profile:
            config = json.loads(Path(profile).read_text())
            self.voice_id = config["voice_id"]
            self.model_id = config.get("model_id", self.model_id)
            self.settings = config.get("voice_settings", self.settings)
            self.requires_verification = bool(config.get("requires_verification", False))
        if not isinstance(self.settings, dict):
            raise ValueError("voice_settings must be an object")

    @property
    def available(self):
        return bool(self.api_key and self.voice_id and not self.requires_verification)

    def synthesize(self, text):
        if not self.available:
            raise SpeechUnavailable("ElevenLabs is not configured; use browser speech")
        if not text.strip() or len(text) > 280:
            raise ValueError("Speech text must contain 1–280 characters")
        body = dict(text=text, model_id=self.model_id, voice_settings=self.settings)
        digest = hashlib.sha256(json.dumps(dict(voice_id=self.voice_id, **body), sort_keys=True).encode()).hexdigest()
        output = self.cache_dir / f"{digest}.mp3"
        if output.exists():
            return output.read_bytes()
        request = Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{quote(self.voice_id, safe='')}?output_format=mp3_44100_128",
            data=json.dumps(body).encode(),
            headers={"xi-api-key": self.api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                content_type = response.headers.get("Content-Type", "")
                audio = response.read(8 * 1024 * 1024 + 1)
            if "audio" not in content_type or not audio or len(audio) > 8 * 1024 * 1024:
                raise SpeechUnavailable("Speech service returned invalid audio")
        except HTTPError as error:
            # Do not echo remote bodies, API keys, or voice-bank information.
            raise SpeechUnavailable(f"ElevenLabs returned HTTP {error.code}; use browser speech") from error
        except (URLError, TimeoutError, OSError) as error:
            raise SpeechUnavailable("Speech service unreachable; use browser speech") from error
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.cache_dir, delete=False) as stream:
            stream.write(audio)
            temporary = Path(stream.name)
        temporary.replace(output)
        return audio
