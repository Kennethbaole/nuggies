"""Dry-run-first IVC upload helper. Never part of normal app startup."""

import argparse
import json
import os
from pathlib import Path
import secrets
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def read_manifest(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text())
    if not data.get("name") or not isinstance(data.get("samples"), list) or not data["samples"]:
        raise ValueError("Manifest needs name and a nonempty samples list")
    files = []
    for item in data["samples"]:
        sample = (path.parent / item["path"]).resolve()
        if sample.suffix.lower() not in (".wav", ".mp3", ".m4a", ".flac"):
            raise ValueError("Use WAV, MP3, M4A, or FLAC samples")
        if not sample.is_file() or not 0 < sample.stat().st_size <= 20 * 1024 * 1024:
            raise ValueError(f"Missing, empty, or oversized sample: {sample.name}")
        files.append(sample)
    if sum(file.stat().st_size for file in files) > 40 * 1024 * 1024:
        raise ValueError("This helper limits total uploads to 40 MB; use the dashboard for larger banks")
    return data, files


def multipart(name, files):
    boundary = "nuggies-" + secrets.token_hex(16)
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n{name}\r\n'.encode()]
    for file in files:
        # Safe generated upload filenames avoid header injection from local names.
        filename = "sample-" + str(len(parts)) + file.suffix.lower()
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
        parts.append(file.read_bytes()); parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return boundary, b"".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--execute", action="store_true", help="Upload to ElevenLabs; may use account quota")
    parser.add_argument("--rights-confirmed", action="store_true", help="Confirm permission and consent for this voice")
    parser.add_argument("--output", default="config/voice_profile.local.json")
    args = parser.parse_args()
    try:
        manifest, files = read_manifest(args.manifest)
        print(f"Validated {len(files)} local samples, {sum(f.stat().st_size for f in files)} bytes. No upload yet.")
        if not args.execute:
            return
        if not args.rights_confirmed:
            parser.error("Upload requires --rights-confirmed for this authorized voice")
        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            parser.error("Export ELEVENLABS_API_KEY before uploading")
        output = Path(args.output)
        if output.exists():
            parser.error("Output profile already exists; choose a new path")
        boundary, body = multipart(manifest["name"], files)
        request = Request("https://api.elevenlabs.io/v1/voices/add", data=body,
                          headers={"xi-api-key": api_key, "Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
        with urlopen(request, timeout=60) as response:
            result = json.load(response)
        if result.get("requires_verification"):
            print("The provider requires verification. Complete it in your account before using this voice.")
        profile = dict(voice_id=result["voice_id"], model_id="eleven_multilingual_v2",
                       requires_verification=bool(result.get("requires_verification")))
        with output.open("x") as stream:
            json.dump(profile, stream, indent=2)
        print(f"Created voice profile at {output}. No app speech has been generated.")
    except HTTPError as error:
        raise SystemExit(f"ElevenLabs returned HTTP {error.code}; review the account/API configuration") from error
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
