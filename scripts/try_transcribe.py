"""Check the Jetson's Qwen speech-to-text from this computer, without the web app.

    python -m scripts.try_transcribe --health          # is the service (and tunnel) up?
    python -m scripts.try_transcribe --wav question.wav
    python -m scripts.try_transcribe --record 5        # speak into this computer's mic

Uses ASR_URL / ASR_TOKEN from .env. Prints the transcript, the detected
language and the round-trip latency. Nothing is stored.
"""

import argparse
import json
from pathlib import Path

from backend.envfile import load_env
from backend.transcribe import RemoteTranscriber, TranscriptionUnavailable
from scripts.try_suggest import record


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--health", action="store_true", help="Only check that the service answers")
    source.add_argument("--wav", help="Audio file (anything ffmpeg reads)")
    source.add_argument("--record", type=float, metavar="SECONDS", help="Record from the default microphone")
    args = parser.parse_args()
    load_env()
    client = RemoteTranscriber()
    if not client.available:
        raise SystemExit("Set ASR_URL in .env first (e.g. http://127.0.0.1:8000 through an SSH tunnel)")
    try:
        if args.health:
            print(json.dumps(client.health(), indent=2))
            return
        audio = Path(args.wav).read_bytes() if args.wav else record(args.record)
        result = client.transcribe(audio, "audio/wav")
    except (TranscriptionUnavailable, ValueError, OSError) as error:
        raise SystemExit(str(error)) from error
    print(f"{result.latency_ms} ms · {result.model or 'unknown model'} · {result.language or 'language unknown'}")
    print(f"Heard: {result.text or '(no speech)'}")


if __name__ == "__main__":
    main()
