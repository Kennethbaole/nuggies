import base64
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend import asr_server
from backend.app import Application, make_handler
from backend.suggestions import OllamaSuggestions, SuggestionUnavailable
from backend.transcribe import RemoteTranscriber, TranscriptionUnavailable

patch("backend.app.load_env").start()
patch("backend.speech.load_env").start()
patch("backend.suggestions.load_env").start()
patch("backend.transcribe.load_env").start()

GOOD = {"heard": "ignored", "suggestions": [{"label": "Yes", "text": "Yes, tea would be lovely."}]}


def transcriber(response=None, error=None, url="http://jetson:8000", token=""):
    calls = []

    def transport(url, headers, body, timeout):
        calls.append((url, headers, body, timeout))
        if error:
            raise error
        return response

    client = RemoteTranscriber(transport=transport, timeout=5)
    client.url, client.token = url, token
    return client, calls


class ClientTests(unittest.TestCase):
    def test_request_shape_and_result(self):
        client, calls = transcriber(dict(text="  Do you want   tea? ", language="English", model="Qwen/Qwen3-ASR-0.6B"),
                                    token="secret")
        result = client.transcribe(b"audio-bytes", "audio/webm;codecs=opus")
        url, headers, body, timeout = calls[0]
        self.assertEqual(url, "http://jetson:8000/transcribe")
        self.assertEqual(headers["Authorization"], "Bearer secret")
        self.assertEqual(base64.b64decode(body["audio_b64"]), b"audio-bytes")
        self.assertEqual(body["mime_type"], "audio/webm;codecs=opus")
        self.assertEqual(timeout, 5)
        self.assertEqual((result.text, result.language), ("Do you want tea?", "English"))

    def test_unconfigured_invalid_and_failures(self):
        client, calls = transcriber(url="")
        self.assertFalse(client.available)
        with self.assertRaises(TranscriptionUnavailable):
            client.transcribe(b"x")
        self.assertEqual(calls, [])
        with self.assertRaises(ValueError):
            transcriber()[0].transcribe(b"")
        for error, message in ((URLError("down"), "tunnel"), (TimeoutError(), "tunnel"),
                               (HTTPError("u", 401, "no", {}, None), "token"), (HTTPError("u", 429, "busy", {}, None), "busy")):
            with self.assertRaisesRegex(TranscriptionUnavailable, message):
                transcriber(error=error)[0].transcribe(b"x")
        for bad in (None, [], {"text": 3}):
            with self.assertRaises(TranscriptionUnavailable):
                transcriber(bad)[0].transcribe(b"x")

    def test_rejects_non_http_url(self):
        with patch.dict("os.environ", {"ASR_URL": "ftp://jetson"}):
            with self.assertRaises(ValueError):
                RemoteTranscriber()


class AppTests(unittest.TestCase):
    def make_app(self, transcript=None, error=None):
        app = Application()
        self.suggest_calls = []
        app.suggester = OllamaSuggestions(mode="single", transport=lambda *args: (
            self.suggest_calls.append(args), {"message": {"content": json.dumps(GOOD)}})[1])
        app.suggester.model = "qwen3:1.7b"
        app.transcriber, self.asr_calls = transcriber(transcript, error)
        return app

    def audio_payload(self, app):
        return dict(session_id=app.session_id, mime_type="audio/webm", audio_b64=base64.b64encode(b"speech").decode())

    def test_audio_is_transcribed_by_qwen_and_sent_as_text(self):
        app = self.make_app(dict(text="Do you want some tea?", language="English"))
        state = app.suggest(self.audio_payload(app))
        self.assertEqual(len(self.asr_calls), 1)
        body = self.suggest_calls[0][2]
        self.assertNotIn(base64.b64encode(b"speech").decode(), json.dumps(body))  # The reply model never receives audio.
        self.assertIn("Do you want some tea?", body["messages"][1]["content"])
        self.assertTrue(state["transcribe_available"])
        self.assertEqual(state["slots"][0]["text"], "Yes, tea would be lovely.")

    def test_asr_failure_never_reaches_the_reply_model(self):
        app = self.make_app(error=URLError("tunnel down"))
        with self.assertRaisesRegex(TranscriptionUnavailable, "tunnel up"):
            app.suggest(self.audio_payload(app))
        self.assertEqual(self.suggest_calls, [])
        self.assertEqual(app.state()["suggestions_provider"], "curated-demo")

    def test_listening_needs_asr_url_not_a_reply_model(self):
        app = self.make_app(dict(text="unused"))
        app.transcriber.url = ""
        with self.assertRaisesRegex(TranscriptionUnavailable, "ASR_URL"):
            app.suggest(self.audio_payload(app))
        self.assertEqual(self.suggest_calls, [])
        self.assertFalse(app.state()["transcribe_available"])

    def test_transcript_shown_without_any_reply_model(self):
        app = self.make_app(dict(text="Can you hear me?"))
        app.suggester.model = ""
        self.assertFalse(app.state()["suggest_available"])
        before = app.state()["slots"][0]["text"]
        state = app.suggest(self.audio_payload(app))
        self.assertEqual(state["heard"], "Can you hear me?")
        self.assertEqual(state["suggestions_provider"], "curated-demo")
        self.assertEqual(state["slots"][0]["text"], before)
        self.assertEqual(self.suggest_calls, [])
        with self.assertRaisesRegex(SuggestionUnavailable, "not configured"):
            app.suggest(dict(session_id=app.session_id, heard_text="typed"))

    def test_reply_model_answers_from_qwen_transcript(self):
        app = self.make_app(dict(text="Are you cold?"))
        state = app.suggest(self.audio_payload(app))
        self.assertIn("Are you cold?", self.suggest_calls[0][2]["messages"][1]["content"])
        self.assertEqual(state["heard"], "Are you cold?")
        self.assertEqual(state["suggestions_provider"], "ollama")

    def test_silence_and_typed_text(self):
        app = self.make_app(dict(text=""))
        with self.assertRaisesRegex(SuggestionUnavailable, "No speech"):
            app.suggest(self.audio_payload(app))
        app = self.make_app(dict(text="unused"))
        app.suggest(dict(session_id=app.session_id, heard_text="Typed words"))
        self.assertEqual(self.asr_calls, [])

    def test_transcribe_endpoint(self):
        app = self.make_app(dict(text="Hello there", language="English", model="Qwen/Qwen3-ASR-0.6B"))
        app.token = "tok"
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = Request(f"http://127.0.0.1:{server.server_port}/api/transcribe",
                              data=json.dumps(self.audio_payload(app)).encode(), headers={"Authorization": "Bearer tok"})
            data = json.load(urlopen(request, timeout=5))
            self.assertEqual(data["text"], "Hello there")
            self.assertEqual(app.state()["suggestions_provider"], "curated-demo")
            app.transcriber.url = ""
            with self.assertRaises(HTTPError) as error:
                urlopen(request, timeout=5)
            error.exception.close()
            self.assertEqual(error.exception.code, 503)
        finally:
            server.shutdown(); server.server_close(); thread.join()


class FakeEngine:
    model_id, device = "Qwen/Qwen3-ASR-0.6B", "cpu"

    def __init__(self):
        self.pcm = []

    def transcribe(self, pcm):
        self.pcm.append(pcm)
        return "hello there", "English"


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.engine = FakeEngine()
        self.service = asr_server.Service(self.engine, token="tok", decode=lambda audio: b"\x00\x00" * 8000)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), asr_server.make_handler(self.service))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def client(self, token="tok"):
        client = RemoteTranscriber(timeout=5)
        client.url, client.token = f"http://127.0.0.1:{self.server.server_port}", token
        return client

    def test_round_trip_through_real_client(self):
        result = self.client().transcribe(b"webm-bytes", "audio/webm")
        self.assertEqual((result.text, result.language), ("hello there", "English"))
        self.assertEqual(self.client().health()["model"], "Qwen/Qwen3-ASR-0.6B")

    def test_token_bad_audio_and_busy(self):
        with self.assertRaisesRegex(TranscriptionUnavailable, "token"):
            self.client(token="wrong").transcribe(b"x")
        with self.assertRaisesRegex(TranscriptionUnavailable, "HTTP 400"):
            self.client().call("/transcribe", dict(audio_b64="***"))
        self.service.lock.acquire()
        try:
            with self.assertRaisesRegex(TranscriptionUnavailable, "busy"):
                self.client().transcribe(b"x")
        finally:
            self.service.lock.release()
        self.assertEqual(self.engine.pcm, [])

    def test_undecodable_audio_is_a_client_error(self):
        def bad(audio):
            raise ValueError("Audio could not be decoded")
        self.service.decode = bad
        with self.assertRaisesRegex(TranscriptionUnavailable, "HTTP 400"):
            self.client().transcribe(b"x")

    def test_decode_audio_reports_missing_ffmpeg(self):
        with self.assertRaisesRegex(RuntimeError, "ffmpeg"):
            asr_server.decode_audio(b"x", ffmpeg="definitely-not-ffmpeg-binary")

    def test_language_is_normalized_or_rejected_before_loading(self):
        supported = ["Chinese", "English"]
        self.assertIsNone(asr_server.check_language(None, supported))
        self.assertIsNone(asr_server.check_language("  ", supported))
        self.assertEqual(asr_server.check_language(" english ", supported), "English")
        with self.assertRaisesRegex(RuntimeError, "Englsh.*English"):
            asr_server.check_language("Englsh", supported)



class LauncherTests(unittest.TestCase):
    def test_plan_asr(self):
        from scripts.dev import plan_asr
        self.assertEqual(plan_asr("", False), "off")
        self.assertEqual(plan_asr("http://127.0.0.1:8000", False, no_asr=True), "off")
        self.assertEqual(plan_asr("http://127.0.0.1:8000", True), "existing")  # e.g. an SSH tunnel
        self.assertEqual(plan_asr("http://127.0.0.1:8000", False), "local")
        self.assertEqual(plan_asr("http://100.64.0.5:8000", False), "unreachable")

if __name__ == "__main__":
    unittest.main()
