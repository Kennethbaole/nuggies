import array
import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from backend.envfile import load_env
from scripts.create_voice import read_manifest
from scripts.record_voice import default_prompts, level_warning, peak_level, save_wav, write_manifest


class EnvFileTests(unittest.TestCase):
    def test_loads_values_but_never_overrides_the_shell(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text('# comment\nELEVENLABS_API_KEY="abc"\nexport VOICE_X=1\nEMPTY=\nKEEP=file\n')
            with patch.dict(os.environ, {"KEEP": "shell"}, clear=False):
                os.environ.pop("ELEVENLABS_API_KEY", None)
                os.environ.pop("VOICE_X", None)
                loaded = load_env(path)
                self.assertEqual(os.environ["ELEVENLABS_API_KEY"], "abc")
                self.assertEqual(os.environ["VOICE_X"], "1")
                self.assertEqual(os.environ["KEEP"], "shell")
                self.assertNotIn("EMPTY", loaded)
                os.environ.pop("ELEVENLABS_API_KEY"); os.environ.pop("VOICE_X")

    def test_missing_file_is_fine(self):
        self.assertEqual(load_env("does-not-exist.env"), [])


class RecordVoiceTests(unittest.TestCase):
    def test_levels(self):
        loud = array.array("h", [0, -32767, 10]).tobytes()
        self.assertEqual(peak_level(loud), 32767)
        self.assertIn("clipping", level_warning(32767))
        self.assertIn("quiet", level_warning(100))
        self.assertIsNone(level_warning(12000))
        self.assertEqual(peak_level(b""), 0)

    def test_wav_refuses_overwrite_and_manifest_feeds_create_voice(self):
        pcm = array.array("h", [1000] * 4410).tobytes()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "voicebank").mkdir()
            (root / "config").mkdir()
            wav_path = root / "voicebank" / "sample-01.wav"
            save_wav(wav_path, pcm, 44100)
            with self.assertRaises(FileExistsError):
                save_wav(wav_path, pcm, 44100)
            with wave.open(str(wav_path)) as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 44100))
            manifest = root / "config" / "voice_bank.local.json"
            write_manifest(manifest, "Test", [(wav_path, "Hello there.")], "en")
            data, files = read_manifest(manifest)  # the validator create_voice runs first
            self.assertEqual(data["name"], "Test")
            self.assertEqual(files, [wav_path.resolve()])
            self.assertEqual(json.loads(manifest.read_text())["samples"][0]["path"], "../voicebank/sample-01.wav")
            self.assertEqual(wav_path.with_suffix(".txt").read_text().strip(), "Hello there.")

    def test_default_prompts_come_from_the_app_phrases(self):
        prompts = default_prompts()
        self.assertGreaterEqual(len(prompts), 8)
        self.assertIn("I love you.", prompts)


if __name__ == "__main__":
    unittest.main()
