"""Explicitly pre-generate configured phrases; may consume ElevenLabs quota."""

import json
from pathlib import Path

from backend.speech import ElevenLabsSpeech


def main():
    provider = ElevenLabsSpeech()
    if not provider.available:
        raise SystemExit("Export the API key and authorized voice configuration first")
    config = json.loads(Path("config/phrases.json").read_text())
    for item in config["phrases"] + config["needs"]:
        audio = provider.synthesize(item["text"])
        print(f"Cached {item['id']}: {len(audio)} bytes")


if __name__ == "__main__":
    main()
