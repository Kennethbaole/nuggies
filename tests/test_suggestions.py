import base64
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app import Application, make_handler
from backend.suggestions import (
    GeminiSuggestions, SuggestionBusy, SuggestionUnavailable, clean_suggestions, normalize_audio_type,
)


def reply(payload):
    return {"candidates": [{"content": {"parts": [{"text": payload if isinstance(payload, str) else json.dumps(payload)}]}}]}


GOOD = {"heard": "Do you want some tea?", "suggestions": [
    {"label": "Yes please", "text": "Yes, tea would be lovely."},
    {"label": "No thanks", "text": "No thank you, I am fine."},
    {"label": "Later", "text": "Maybe in a little while."},
    {"label": "What kind", "text": "What kind of tea do you have?"},
    {"label": "Sweet of you", "text": "That is very kind of you to ask."},
]}


SECOND = {"heard": "", "suggestions": [
    {"label": "Sounds good", "text": "That sounds good to me."},
    {"label": "Tell me", "text": "Tell me more about that."},
]}


def provider(response=None, error=None, key="test-key"):
    calls = []

    def transport(url, headers, body, timeout):
        calls.append((url, headers, body, timeout))
        if error:
            raise error
        return response

    suggester = GeminiSuggestions(transport=transport)
    suggester.api_key = key
    return suggester, calls


class CleanTests(unittest.TestCase):
    def test_dedupes_bounds_and_skips_used_text(self):
        items = [dict(label="A very long label indeed", text="Hello there."), dict(label="Dup", text="hello   THERE."),
                 dict(label="", text="Thanks a lot."), dict(label="x", text="y" * 281), "junk", dict(label="n", text=None),
                 dict(label="Used", text="Already said.")]
        cleaned = clean_suggestions(items, avoid=["already said."])
        self.assertEqual([item["text"] for item in cleaned], ["Hello there.", "Thanks a lot."])
        self.assertLessEqual(len(cleaned[0]["label"]), 14)
        self.assertEqual(cleaned[1]["label"], "Thanks")
        self.assertTrue(cleaned[0]["id"].startswith("ai-"))

    def test_limits_to_five_and_tolerates_non_lists(self):
        many = [dict(label=str(i), text=f"Reply number {i}.") for i in range(9)]
        self.assertEqual(len(clean_suggestions(many)), 5)
        self.assertEqual(clean_suggestions(None), [])

    def test_audio_type_normalization(self):
        self.assertEqual(normalize_audio_type("audio/webm;codecs=opus"), "audio/webm")
        self.assertEqual(normalize_audio_type("audio/mp4"), "audio/m4a")
        with self.assertRaises(ValueError):
            normalize_audio_type("video/mp4")


class ProviderTests(unittest.TestCase):
    def test_audio_request_shape_and_result(self):
        suggester, calls = provider(reply(GOOD))
        audio = b"\x00\x01fake-audio"
        result = suggester.suggest(contact=dict(name="Alex", relationship="Family"), recent=["I love you."],
                                   audio=audio, mime_type="audio/webm;codecs=opus")
        url, headers, body, _ = calls[0]
        self.assertIn(":generateContent", url)
        self.assertNotIn("test-key", url)  # key travels in a header only
        self.assertEqual(headers["x-goog-api-key"], "test-key")
        parts = body["contents"][0]["parts"]
        inline = next(part["inline_data"] for part in parts if "inline_data" in part)
        self.assertEqual(inline["mime_type"], "audio/webm")
        self.assertEqual(base64.b64decode(inline["data"]), audio)
        self.assertIn("Alex", parts[0]["text"])
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(result.heard, "Do you want some tea?")
        self.assertEqual(len(result.suggestions), 5)

    def test_text_only_and_fenced_json(self):
        suggester, calls = provider(reply("```json\n" + json.dumps(GOOD) + "\n```"))
        result = suggester.suggest(heard_text="How are you?")
        self.assertEqual(len(result.suggestions), 5)
        self.assertNotIn("inline_data", json.dumps(calls[0][2]))

    def test_validation_and_configuration(self):
        suggester, _ = provider(reply(GOOD))
        with self.assertRaises(ValueError):
            suggester.suggest()
        with self.assertRaises(ValueError):
            suggester.suggest(audio=b"x" * 2_600_000, mime_type="audio/wav")
        with self.assertRaises(ValueError):
            suggester.suggest(audio=b"abc", mime_type="text/plain")
        with self.assertRaises(SuggestionUnavailable):
            provider(reply(GOOD), key="")[0].suggest(heard_text="hi")

    def test_failures_become_unavailable_without_leaking_bodies(self):
        error = HTTPError("https://x", 429, "secret-detail", {}, None)
        with self.assertRaises(SuggestionUnavailable) as caught:
            provider(error=error)[0].suggest(heard_text="hi")
        error.close()
        self.assertIn("429", str(caught.exception))
        self.assertNotIn("secret-detail", str(caught.exception))
        for failing in (URLError("down"), TimeoutError()):
            with self.assertRaises(SuggestionUnavailable):
                provider(error=failing)[0].suggest(heard_text="hi")
        for bad in ({}, {"candidates": []}, reply("not json"), reply({"suggestions": []}),
                    {"promptFeedback": {"blockReason": "SAFETY"}}):
            with self.assertRaises(SuggestionUnavailable):
                provider(bad)[0].suggest(heard_text="hi")


class AppIntegrationTests(unittest.TestCase):
    def make_app(self, response=None):
        app = Application()
        app.suggester, self.calls = provider(reply(GOOD) if response is None else response)
        return app

    def test_suggestions_replace_home_pool_but_never_speak(self):
        app = self.make_app()
        state = app.suggest(dict(session_id=app.session_id, heard_text="Do you want some tea?"))
        self.assertEqual(state["suggestions_provider"], "gemini")
        self.assertEqual(state["heard"], "Do you want some tea?")
        self.assertEqual(state["slots"][0]["text"], "Yes, tea would be lovely.")
        self.assertEqual(state["selection_id"], 0)
        self.assertEqual(state["confirmed"], "")
        selected = app.command(dict(action="select", event_id="pick"))
        self.assertEqual(selected["confirmed"], "Yes, tea would be lovely.")

    def test_inflight_suggestions_do_not_override_new_context(self):
        app = self.make_app()
        other = app.ring.config["contacts"][1]["id"]
        def change_context(*args):
            app.command(dict(action="contact", value=other, event_id="during-generation"))
            return reply(GOOD)
        app.suggester.transport = change_context
        with self.assertRaisesRegex(SuggestionUnavailable, "Conversation changed"):
            app.suggest(dict(session_id=app.session_id, heard_text="hi"))
        self.assertEqual(app.state()["contact"], other)
        self.assertEqual(app.state()["suggestions_provider"], "curated-demo")
        self.assertEqual(app.state()["selection_id"], 0)

    def test_clear_contact_change_and_session_check(self):
        app = self.make_app()
        app.suggest(dict(session_id=app.session_id, heard_text="hi"))
        cleared = app.command(dict(action="suggestions_clear", event_id="clear"))
        self.assertEqual(cleared["suggestions_provider"], "curated-demo")
        self.assertEqual(cleared["slots"][0]["text"], "Hi, it is good to see you.")
        app.last_suggest = 0
        app.suggester.transport = lambda *args: reply(SECOND)
        app.suggest(dict(session_id=app.session_id, heard_text="hi"))
        other = app.ring.config["contacts"][1]["id"]
        self.assertEqual(app.command(dict(action="contact", value=other, event_id="who"))["suggestions_provider"], "curated-demo")
        with self.assertRaises(ValueError):
            app.suggest(dict(session_id="wrong", heard_text="hi"))
        with self.assertRaises(ValueError):
            app.suggest(dict(session_id=app.session_id, audio_b64="***not base64***"))

    def test_failure_keeps_curated_phrases_and_refreshes_avoid_repeats(self):
        app = self.make_app({})
        with self.assertRaises(SuggestionUnavailable):
            app.suggest(dict(session_id=app.session_id, heard_text="hi"))
        self.assertEqual(app.state()["suggestions_provider"], "curated-demo")
        app = self.make_app()
        app.suggest(dict(session_id=app.session_id, heard_text="hi"))
        app.last_suggest = 0
        app.suggester.transport = lambda *args: (self.calls.append(args), reply(SECOND))[1]
        app.suggest(dict(session_id=app.session_id, heard_text="again"))
        self.assertIn("Yes, tea would be lovely.", self.calls[-1][2]["contents"][0]["parts"][0]["text"])
        self.assertEqual(app.state()["slots"][0]["text"], "That sounds good to me.")
        with self.assertRaises(SuggestionBusy):
            app.suggest(dict(session_id=app.session_id, heard_text="too soon"))

    def test_http_endpoint_audio_body_limit_and_unavailable(self):
        app = self.make_app()
        app.token = "tok"
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def post(payload):
                return urlopen(Request(f"http://127.0.0.1:{server.server_port}/api/suggest",
                                       data=json.dumps(payload).encode(), headers={"Authorization": "Bearer tok"}), timeout=5)
            audio = base64.b64encode(b"x" * 100_000).decode()  # far above the 4 KB action limit
            state = json.load(post(dict(session_id=app.session_id, mime_type="audio/webm", audio_b64=audio)))
            self.assertEqual(state["suggestions_provider"], "gemini")
            app.suggester.api_key = ""
            with self.assertRaises(HTTPError) as error:
                post(dict(session_id=app.session_id, heard_text="hi"))
            error.exception.close()
            self.assertEqual(error.exception.code, 503)
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == "__main__":
    unittest.main()
