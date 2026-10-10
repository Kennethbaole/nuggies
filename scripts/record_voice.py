"""Record your own voice-bank samples from the microphone (Windows/macOS/Linux).

Reads each prompt aloud; saves one WAV per prompt under voicebank/ and writes a
manifest that scripts.create_voice accepts. Nothing is uploaded by this script.

    python -m scripts.record_voice --list-devices
    python -m scripts.record_voice --name "My voice" --limit 12
"""

import argparse
import array
import json
import os
from pathlib import Path
import threading
import wave

CLIP_LEVEL = 32000   # int16 peak at or above this is probably clipped
QUIET_LEVEL = 2000   # int16 peak below this is probably too quiet


def default_prompts(phrases_path: str = "config/phrases.json") -> list[str]:
    """Use the app's own phrases so the sample resembles what it will say."""
    config = json.loads(Path(phrases_path).read_text())
    return [item["text"] for item in config["phrases"] + config["needs"]]


def peak_level(pcm: bytes) -> int:
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    return max((abs(s) for s in samples), default=0)


def level_warning(peak: int) -> str | None:
    if peak >= CLIP_LEVEL:
        return "clipping: move back from the mic or lower the input volume"
    if peak < QUIET_LEVEL:
        return "very quiet: move closer to the mic or raise the input volume"
    return None


def save_wav(path: Path, pcm: bytes, sample_rate: int) -> None:
    """Write mono 16-bit PCM; never replaces an existing recording."""
    with path.open("xb") as stream, wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)


def write_manifest(path: Path, name: str, entries: list[tuple[Path, str]], language: str) -> None:
    """entries are (wav path, prompt text); paths are stored relative to the manifest."""
    samples = []
    for wav_path, text in entries:
        transcript = wav_path.with_suffix(".txt")
        transcript.write_text(text + "\n", encoding="utf-8")
        samples.append(dict(
            path=Path(os.path.relpath(wav_path, path.parent)).as_posix(),
            transcript_path=Path(os.path.relpath(transcript, path.parent)).as_posix(),
            style="read aloud"))
    manifest = dict(name=name, speaker_reference="local", language=language, samples=samples,
                    consent_record="Keep the actual consent record privately",
                    note="Recorded by scripts.record_voice. Transcripts stay local.")
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def record_clip(sd, device, sample_rate: int) -> bytes:
    chunks: list[bytes] = []
    with sd.RawInputStream(samplerate=sample_rate, channels=1, dtype="int16", device=device,
                           callback=lambda data, frames, time, status: chunks.append(bytes(data))):
        stop = threading.Event()
        threading.Thread(target=lambda: (input("  Recording... press Enter to stop "), stop.set()),
                         daemon=True).start()
        stop.wait()
    return b"".join(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list-devices", action="store_true", help="Show input devices and exit")
    parser.add_argument("--device", help="Input device index or name substring (default: system mic)")
    parser.add_argument("--name", default="My voice", help="Voice name for the manifest")
    parser.add_argument("--language", default="en")
    parser.add_argument("--sample-rate", type=int, default=44100)
    parser.add_argument("--limit", type=int, help="Record only the first N prompts")
    parser.add_argument("--prompts", help="Text file with one prompt per line (default: config/phrases.json)")
    parser.add_argument("--output-dir", default="voicebank")
    parser.add_argument("--manifest", default="config/voice_bank.local.json")
    args = parser.parse_args()
    try:
        import sounddevice as sd
    except (ImportError, OSError) as error:
        raise SystemExit("Mic recording needs sounddevice: pip install -r requirements-voice.txt") from error
    if args.list_devices:
        print(sd.query_devices())
        return
    device = int(args.device) if args.device and args.device.isdigit() else args.device
    manifest = Path(args.manifest)
    if manifest.exists():
        raise SystemExit(f"{manifest} already exists; choose --manifest or remove it first")
    prompts = ([line.strip() for line in Path(args.prompts).read_text(encoding="utf-8").splitlines() if line.strip()]
               if args.prompts else default_prompts())[: args.limit]
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    print("Use a quiet room, the same mic position, and a natural speaking voice.")
    print("For each line: Enter to start, read it aloud, Enter to stop. Type r to redo, s to skip, q to finish.\n")
    entries: list[tuple[Path, str]] = []
    seconds = 0.0
    for index, text in enumerate(prompts, 1):
        while True:
            print(f"[{index}/{len(prompts)}] {text}")
            answer = input("  Enter to record (s skip, q finish): ").strip().lower()
            if answer in ("s", "q"):
                break
            pcm = record_clip(sd, device, args.sample_rate)
            peak, length = peak_level(pcm), len(pcm) / 2 / args.sample_rate
            warning = level_warning(peak)
            print(f"  {length:.1f}s, peak {peak}/32767" + (f"  WARNING {warning}" if warning else ""))
            if length < 0.5 or input("  Keep this take? [Y/n] ").strip().lower() == "n":
                continue
            wav_path = out_dir / f"sample-{index:02d}.wav"
            save_wav(wav_path, pcm, args.sample_rate)
            entries.append((wav_path, text))
            seconds += length
            break
        if answer == "q":
            break
    if not entries:
        raise SystemExit("No samples recorded; manifest not written.")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    write_manifest(manifest, args.name, entries, args.language)
    print(f"\nSaved {len(entries)} samples ({seconds:.0f}s of audio) and {manifest}.")
    print("Validate (no upload):  python -m scripts.create_voice " + manifest.as_posix())


if __name__ == "__main__":
    main()
