import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.app import Application, make_handler
from backend.speech import ElevenLabsSpeech, SpeechUnavailable

# Tests must not read a developer's real .env (keys, voice IDs).
patch("backend.app.load_env").start()
patch("backend.speech.load_env").start()
patch("backend.suggestions.load_env").start()


class ApplicationTests(unittest.TestCase):
    def test_env_loaded_before_session_token(self):
        with patch.dict(os.environ, {}, clear=True), patch("backend.app.load_env", side_effect=lambda: os.environ.update(APP_TOKEN="local-test-token")):
            self.assertEqual(Application().token, "local-test-token")

    def test_action_dedup_and_validation(self):
        app = Application()
        command = dict(action="select", event_id="one")
        app.command(command); app.command(command)
        self.assertEqual(app.state()["selection_id"], 1)
        with self.assertRaises(ValueError):
            app.command(dict(action="focus", value=99, event_id="two"))
        with self.assertRaises(ValueError):
            app.command(dict(action="demo", value="false", event_id="three"))

    def test_raw_counts_cannot_drive_ring_without_opt_in(self):
        from backend.serial_input import ADCSample
        app = Application(source="serial")
        app.ingest(ADCSample(16383, 0, 0)); app.ingest(ADCSample(16383, 0, 100))
        self.assertEqual(app.state()["selected"], 0)
        self.assertFalse(app.state()["sensor_actions"])

    def test_trial_label_is_metadata_and_invalid_label_rejected(self):
        app = Application()
        before = app.state()
        state = app.command(dict(action="label", value="left", event_id="trial"))
        self.assertEqual(state["trial_label"], "left")
        self.assertEqual(state["selection_id"], before["selection_id"])
        self.assertEqual(state["selected"], before["selected"])
        with self.assertRaises(ValueError):
            app.command(dict(action="label", value="invented", event_id="bad-trial"))
        self.assertEqual(app.state()["trial_label"], "left")

    @unittest.skipUnless(__import__("importlib.util", fromlist=["find_spec"]).find_spec("serial"), "pyserial optional")
    def test_serial_recording_writes_intended_label_sidecar(self):
        import csv
        from pathlib import Path
        from backend.serial_input import ADCSample
        app = Application(source="serial")
        app.command(dict(action="label", value="neutral", event_id="trial-capture"))
        def read_once():
            app.stop.set()
            return ADCSample(8000, 8100, 123456)
        with tempfile.TemporaryDirectory() as directory, patch("serial.Serial"), patch("backend.serial_input.SerialADCSource") as source:
            source.return_value.read_sample.side_effect = read_once
            output = Path(directory) / "trial.csv"
            app.run_serial("fake-port", output)
            self.assertEqual(app.error, "")
            with output.open() as stream:
                rows = list(csv.DictReader(stream))
            with output.with_suffix(".labels.csv").open() as stream:
                labels = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["horizontal_adc"], "8000")
            self.assertEqual(labels, [{"timestamp_ms": "123456", "intended_label": "neutral"}])


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Application()
        cls.app.token = "test-token"
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.app))
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.worker.join()

    def request(self, path, payload=None, token="test-token", origin=None):
        headers = {"Authorization": f"Bearer {token}"}
        if origin:
            headers["Origin"] = origin
        return urlopen(Request(self.url + path, headers=headers,
                               data=json.dumps(payload).encode() if payload is not None else None), timeout=3)

    def test_token_and_cross_origin_rejection(self):
        with self.assertRaises(HTTPError) as error:
            self.request("/api/state", token="wrong")
        error.exception.close()
        self.assertEqual(error.exception.code, 401)
        with self.assertRaises(HTTPError) as error:
            self.request("/api/action", dict(action="select", event_id="cross-origin"), origin="https://example.com")
        error.exception.close()
        self.assertEqual(error.exception.code, 403)

    def test_confirmed_speech_only_and_duplicate_claim(self):
        state = json.load(self.request("/api/action", dict(action="select", event_id="http-select")))
        payload = dict(selection_id=state["selection_id"], session_id=state["session_id"])
        with patch.object(self.app.speech, "api_key", ""):
            result = json.load(self.request("/api/speech", payload))
            self.assertEqual(result["provider"], "browser")
            self.assertEqual(result["text"], state["confirmed"])
        with self.assertRaises(HTTPError) as error:
            self.request("/api/speech", payload)
        error.exception.close()
        self.assertEqual(error.exception.code, 409)
        with self.assertRaises(HTTPError) as error:
            self.request("/api/speech", dict(selection_id=99999, session_id=state["session_id"]))
        error.exception.close()
        self.assertEqual(error.exception.code, 400)

    def test_static_only_serves_frontend(self):
        self.assertIn(b"Nuggies", self.request("/").read())
        with self.assertRaises(HTTPError) as error:
            self.request("/../config/voice_profile.example.json")
        error.exception.close()
        self.assertEqual(error.exception.code, 404)


class SpeechTests(unittest.TestCase):
    def test_missing_configuration_never_calls_cloud(self):
        with patch.dict(os.environ, {}, clear=True), patch("backend.speech.urlopen") as remote:
            speech = ElevenLabsSpeech()
            with self.assertRaises(SpeechUnavailable):
                speech.synthesize("Hello")
            remote.assert_not_called()

    def test_cache_separates_voice_and_text_and_settings(self):
        with tempfile.TemporaryDirectory() as path, patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test", "ELEVENLABS_VOICE_ID": "voice"}, clear=True):
            speech = ElevenLabsSpeech(path)
            with patch("backend.speech.urlopen") as remote:
                response = remote.return_value.__enter__.return_value
                response.headers = {"Content-Type": "audio/mpeg"}
                response.read.return_value = b"fake-audio"
                self.assertEqual(speech.synthesize("Hello"), b"fake-audio")
                speech.synthesize("Hello")
                self.assertEqual(remote.call_count, 1)
                speech.settings["stability"] = 0.8
                speech.synthesize("Hello")
                speech.voice_id = "other"
                speech.synthesize("Hello")
                speech.synthesize("Other sentence")
                self.assertEqual(remote.call_count, 4)

    def test_unverified_profile_disables_cloud(self):
        with tempfile.TemporaryDirectory() as path:
            profile = os.path.join(path, "profile.json")
            with open(profile, "w") as stream:
                json.dump(dict(voice_id="voice", requires_verification=True), stream)
            with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test", "VOICE_PROFILE_PATH": profile}, clear=True), patch("backend.speech.urlopen") as remote:
                speech = ElevenLabsSpeech(path)
                self.assertFalse(speech.available)
                with self.assertRaises(SpeechUnavailable):
                    speech.synthesize("Hello")
                remote.assert_not_called()

class RecordingLifecycleTests(unittest.TestCase):
    def test_stop_recording_keeps_acquisition_and_sidecars_aligned(self):
        import csv
        from pathlib import Path
        from backend.serial_input import ADCSample
        app = Application(source='serial')
        reads = 0
        def read_sample():
            nonlocal reads
            reads += 1
            if reads == 2:
                app.command(dict(action='record_stop', event_id='stop-capture'))
            if reads == 3: app.stop.set()
            return ADCSample(8000 + reads, 8100, reads)
        with tempfile.TemporaryDirectory() as directory, patch('serial.Serial'), patch('backend.serial_input.SerialADCSource') as source:
            source.return_value.read_sample.side_effect = read_sample
            output = Path(directory)/'capture.csv'
            app.run_serial('fake-port', output)
            with output.open() as f: raw = list(csv.DictReader(f))
            for suffix in ('.labels.csv', '.trials.csv'):
                with output.with_suffix(suffix).open() as f: rows = list(csv.DictReader(f))
                self.assertEqual(len(rows), len(raw))
            self.assertEqual(len(raw), 1)
            self.assertEqual(len(app.samples), 3)
            self.assertFalse(app.recording)
            self.assertTrue(app.connected)
            self.assertEqual(app.error, '')
