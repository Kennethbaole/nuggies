"""Try Gemini reply suggestions from the terminal, without the web app.

    python -m scripts.try_suggest --text "Do you want some tea?"
    python -m scripts.try_suggest --wav question.wav
    python -m scripts.try_suggest --record 5            # speak, or play audio near the mic
    python -m scripts.try_suggest --text "Hi" --model gemini-3.5-flash-lite

Sends the text/audio you give it to Gemini (uses API quota); prints the latency,
what Gemini heard, and the five previews. Nothing is spoken.
"""

import argparse
import os
from pathlib import Path

from backend.envfile import load_env
from backend.suggestions import GeminiSuggestions, SuggestionUnavailable


def record(seconds, sample_rate=16000):
    import io
    import wave
    try:
        import sounddevice as sd
    except (ImportError, OSError) as error:
        raise SystemExit("Recording needs sounddevice: pip install -r requirements-voice.txt") from error
    print(f"Recording {seconds}s... speak now.", flush=True)
    pcm = sd.rec(int(seconds * sample_rate), samplerate=sample_rate, channels=1, dtype="int16")
    sd.wait()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return buffer.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="What the other person said")
    source.add_argument("--wav", help="Audio file (wav/mp3/ogg/flac/m4a/webm)")
    source.add_argument("--record", type=float, metavar="SECONDS", help="Record from the default microphone")
    parser.add_argument("--model", help="Override GEMINI_MODEL for this run")
    parser.add_argument("--name", default="Alex")
    parser.add_argument("--relationship", default="Family")
    args = parser.parse_args()
    load_env()
    if args.model:
        os.environ["GEMINI_MODEL"] = args.model
    suggester = GeminiSuggestions()
    if not suggester.available:
        raise SystemExit("Set GEMINI_API_KEY in .env first")
    contact = dict(name=args.name, relationship=args.relationship)
    try:
        if args.text:
            result = suggester.suggest(contact=contact, heard_text=args.text)
        elif args.wav:
            path = Path(args.wav)
            kind = {".wav": "audio/wav", ".mp3": "audio/mp3", ".ogg": "audio/ogg", ".flac": "audio/flac",
                    ".m4a": "audio/m4a", ".webm": "audio/webm", ".aac": "audio/aac"}.get(path.suffix.lower())
            if kind is None:
                raise SystemExit("Unsupported file type")
            result = suggester.suggest(contact=contact, audio=path.read_bytes(), mime_type=kind)
        else:
            result = suggester.suggest(contact=contact, audio=record(args.record), mime_type="audio/wav")
    except (SuggestionUnavailable, ValueError) as error:
        raise SystemExit(str(error)) from error
    print(f"\nModel {result.model}, {result.latency_ms} ms")
    print(f"Heard: {result.heard or '(nothing)'}\n")
    for item in result.suggestions:
        print(f"  [{item['label']}] {item['text']}")


if __name__ == "__main__":
    main()
