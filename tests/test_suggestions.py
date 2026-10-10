import base64
import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app import Application, make_handler
from backend.suggestions import (
    FallbackSuggestions, GeminiSuggestions, OllamaSuggestions, SuggestionBusy, SuggestionResult,
    SuggestionUnavailable, clean_suggestions, normalize_audio_type,
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

    def test_label_from_text_uses_reply_opening_words(self):
        items = [dict(label="REPLY-1", text="Can you call her for me, please?"),
                 dict(label="Agree", text="Yes, please."), dict(text="Congratulations, everyone!")]
        self.assertEqual([item["label"] for item in clean_suggestions(items, label_from_text=True)],
                         ["Can you call", "Yes, please", "Congratulation"])
        self.assertEqual(clean_suggestions(items)[0]["label"], "REPLY-1")

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
        app.transcriber.url = "http://jetson:8000"
        app.transcriber.transport = lambda *args: dict(text="Do you want some tea?")
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


def local_provider(response=None, error=None, model="llama3.2:3b"):
    calls = []

    def transport(url, headers, body, timeout):
        calls.append((url, headers, body, timeout))
        if error:
            raise error
        return response

    suggester = OllamaSuggestions(transport=transport)
    suggester.model = model
    return suggester, calls


def local_reply(payload):
    return {"message": {"role": "assistant", "content": payload if isinstance(payload, str) else json.dumps(payload)}}


class OllamaProviderTests(unittest.TestCase):
    def test_request_shape_and_result(self):
        suggester, calls = local_provider(local_reply(GOOD))
        result = suggester.suggest(contact=dict(name="Alex", relationship="Family"), heard_text="  Do you want   tea? ")
        url, _, body, _ = calls[0]
        self.assertEqual(url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual((body["model"], body["format"], body["stream"], body["think"]), ("llama3.2:3b", "json", False, False))
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertIn('"Do you want tea?"', body["messages"][1]["content"])
        self.assertIn("Alex", body["messages"][1]["content"])
        self.assertEqual(result.provider, "ollama")
        self.assertEqual(result.heard, "Do you want tea?")
        self.assertEqual(len(result.suggestions), 5)
        self.assertEqual(result.suggestions[0]["label"], "Yes, tea would")  # From the reply, not the model.

    def test_audio_only_unconfigured_and_failures(self):
        suggester, calls = local_provider(local_reply(GOOD))
        with self.assertRaisesRegex(SuggestionUnavailable, "typed text"):
            suggester.suggest(audio=b"abc", mime_type="audio/webm")
        with self.assertRaises(ValueError):
            suggester.suggest()
        self.assertEqual(calls, [])
        with self.assertRaises(SuggestionUnavailable):
            local_provider(local_reply(GOOD), model="")[0].suggest(heard_text="hi")
        for failure in (local_provider(error=URLError("refused"))[0], local_provider(local_reply("not json"))[0],
                        local_provider({"error": "model not found"})[0], local_provider(local_reply({"suggestions": []}))[0]):
            with self.assertRaises(SuggestionUnavailable):
                failure.suggest(heard_text="hi")


class FakeProvider:
    def __init__(self, name, error=None, delay=0.0, available=True):
        self.name, self.error, self.delay, self.available, self.calls = name, error, delay, available, 0

    def suggest(self, **kwargs):
        self.calls += 1
        time.sleep(self.delay)
        if self.error:
            raise self.error
        return SuggestionResult(kwargs.get("heard_text", ""), [dict(id="x", label="L", text=self.name)], self.name, 0, self.name)


def network_failure():
    try:
        raise SuggestionUnavailable("Gemini unreachable") from URLError("offline")
    except SuggestionUnavailable as error:
        return error


class FallbackTests(unittest.TestCase):
    def test_primary_answers_when_healthy(self):
        primary, fallback = FakeProvider("gemini"), FakeProvider("ollama")
        self.assertEqual(FallbackSuggestions(primary, fallback).suggest(heard_text="hi").provider, "gemini")
        self.assertEqual(fallback.calls, 0)

    def test_network_failure_falls_back_and_skips_primary_for_cooldown(self):
        primary, fallback = FakeProvider("gemini", error=network_failure()), FakeProvider("ollama")
        chooser = FallbackSuggestions(primary, fallback)
        self.assertEqual(chooser.suggest(heard_text="hi").provider, "ollama")
        self.assertEqual(chooser.suggest(heard_text="hi").provider, "ollama")
        self.assertEqual(primary.calls, 1)  # Second request did not wait on Gemini again.
        chooser.skip_primary_until = 0.0
        primary.error = None
        self.assertEqual(chooser.suggest(heard_text="hi").provider, "gemini")

    def test_http_error_falls_back_without_cooldown(self):
        try:
            raise SuggestionUnavailable("Gemini returned HTTP 500") from HTTPError("u", 500, "x", {}, None)
        except SuggestionUnavailable as error:
            http_failure = error
        primary, fallback = FakeProvider("gemini", error=http_failure), FakeProvider("ollama")
        chooser = FallbackSuggestions(primary, fallback)
        chooser.suggest(heard_text="hi")
        chooser.suggest(heard_text="hi")
        self.assertEqual((primary.calls, fallback.calls), (2, 2))

    def test_slow_primary_falls_back_at_deadline(self):
        primary, fallback = FakeProvider("gemini", delay=1.0), FakeProvider("ollama")
        chooser = FallbackSuggestions(primary, fallback, deadline_s=0.1)
        started = time.monotonic()
        self.assertEqual(chooser.suggest(heard_text="hi").provider, "ollama")
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertGreater(chooser.skip_primary_until, time.monotonic())

    def test_invalid_input_is_not_retried_locally(self):
        primary, fallback = FakeProvider("gemini", error=ValueError("bad audio")), FakeProvider("ollama")
        with self.assertRaises(ValueError):
            FallbackSuggestions(primary, fallback).suggest(heard_text="hi")
        self.assertEqual(fallback.calls, 0)

    def test_unconfigured_primary_goes_straight_to_fallback(self):
        primary, fallback = FakeProvider("gemini", available=False), FakeProvider("ollama")
        self.assertEqual(FallbackSuggestions(primary, fallback).suggest(heard_text="hi").provider, "ollama")
        self.assertEqual(primary.calls, 0)

    def test_both_failing_or_unconfigured_is_unavailable(self):
        chooser = FallbackSuggestions(FakeProvider("gemini", error=network_failure()),
                                      FakeProvider("ollama", error=SuggestionUnavailable("Local model unreachable")))
        with self.assertRaisesRegex(SuggestionUnavailable, "Local model unreachable"):
            chooser.suggest(heard_text="hi")
        none = FallbackSuggestions(FakeProvider("gemini", available=False), FakeProvider("ollama", available=False))
        self.assertFalse(none.available)
        with self.assertRaises(SuggestionUnavailable):
            none.suggest(heard_text="hi")


class OfflineAppTests(unittest.TestCase):
    def test_offline_gemini_uses_local_model_on_the_ring(self):
        app = Application()
        gemini, _ = provider(error=URLError("offline"))
        local, local_calls = local_provider(local_reply(SECOND))
        app.suggester = FallbackSuggestions(gemini, local)
        state = app.suggest(dict(session_id=app.session_id, heard_text="How was your day?"))
        self.assertEqual(state["suggestions_provider"], "ollama")
        self.assertEqual(state["slots"][0]["text"], "That sounds good to me.")
        self.assertEqual(state["heard"], "How was your day?")
        self.assertEqual(len(local_calls), 1)
        cleared = app.command(dict(action="suggestions_clear", event_id="clear"))
        self.assertEqual(cleared["suggestions_provider"], "curated-demo")


if __name__ == "__main__":
    unittest.main()
