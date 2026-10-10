import base64
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app import Application, make_handler
from backend.suggestions import OllamaSuggestions, SuggestionBusy, SuggestionUnavailable, clean_suggestions


def reply(payload):
    return {"message": {"role": "assistant", "content": payload if isinstance(payload, str) else json.dumps(payload)}}


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


def provider(response=None, error=None, model="qwen3:1.7b"):
    calls = []

    def transport(url, headers, body, timeout):
        calls.append((url, headers, body, timeout))
        if error:
            raise error
        return response

    suggester = OllamaSuggestions(transport=transport)
    suggester.model = model
    return suggester, calls


class CleanTests(unittest.TestCase):
    def test_dedupes_bounds_and_skips_used_text(self):
        items = [dict(label="A very long label indeed", text="Hello there."), dict(label="Dup", text="hello   THERE."),
                 dict(label="", text="Thanks a lot."), dict(label="x", text="y" * 281), "junk", dict(label="n", text=None),
                 dict(label="Used", text="Already said.")]
        cleaned = clean_suggestions(items, avoid=["already said."])
        self.assertEqual([item["text"] for item in cleaned], ["Hello there.", "Thanks a lot."])
        self.assertLessEqual(len(cleaned[0]["label"]), 14)
        self.assertEqual(cleaned[1]["label"], "Thanks a lot")
        self.assertTrue(cleaned[0]["id"].startswith("ai-"))

    def test_labels_come_from_reply_text_not_model(self):
        items = [dict(label="REPLY-1", text="Can you call her for me, please?"),
                 dict(label="Agree", text="Yes, please."),
                 dict(text="Unbelievably wonderful news!"), dict(text="Congratulations, everyone!")]
        self.assertEqual([item["label"] for item in clean_suggestions(items)],
                         ["Can you call", "Yes, please", "Unbelievably", "Congratulation"])

    def test_limits_to_five_and_tolerates_non_lists(self):
        many = [dict(label=str(i), text=f"Reply number {i}.") for i in range(9)]
        self.assertEqual(len(clean_suggestions(many)), 5)
        self.assertEqual(clean_suggestions(None), [])


class ProviderTests(unittest.TestCase):
    def test_request_shape_and_result(self):
        suggester, calls = provider(reply(GOOD))
        result = suggester.suggest(contact=dict(name="Alex", relationship="Family"), heard_text="  Do you want   tea? ")
        url, _, body, _ = calls[0]
        self.assertEqual(url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual((body["model"], body["format"], body["stream"], body["think"]),
                         ("qwen3:1.7b", "json", False, False))
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertIn('"Do you want tea?"', body["messages"][1]["content"])
        self.assertIn("Alex", body["messages"][1]["content"])
        self.assertEqual(result.provider, "ollama")
        self.assertEqual(result.heard, "Do you want tea?")
        self.assertEqual(len(result.suggestions), 5)
        self.assertEqual(result.suggestions[0]["label"], "Yes, tea would")  # From the reply, not the model.
        self.assertNotIn("label", body["messages"][0]["content"])  # The model is not asked to write labels.

    def test_fenced_json(self):
        suggester, _ = provider(reply("```json\n" + json.dumps(GOOD) + "\n```"))
        self.assertEqual(len(suggester.suggest(heard_text="How are you?").suggestions), 5)

    def test_missing_text_unconfigured_and_failures(self):
        suggester, calls = provider(reply(GOOD))
        with self.assertRaises(ValueError):
            suggester.suggest()
        self.assertEqual(calls, [])
        with self.assertRaises(SuggestionUnavailable):
            provider(reply(GOOD), model="")[0].suggest(heard_text="hi")
        error = HTTPError("https://x", 500, "secret-detail", {}, None)
        with self.assertRaises(SuggestionUnavailable) as caught:
            provider(error=error)[0].suggest(heard_text="hi")
        error.close()
        self.assertIn("500", str(caught.exception))
        self.assertNotIn("secret-detail", str(caught.exception))
        for failure in (provider(error=URLError("refused"))[0], provider(error=TimeoutError())[0],
                        provider(reply("not json"))[0], provider({"error": "model not found"})[0],
                        provider(reply({"suggestions": []}))[0]):
            with self.assertRaises(SuggestionUnavailable):
                failure.suggest(heard_text="hi")


class AppIntegrationTests(unittest.TestCase):
    def make_app(self, response=None):
        app = Application()
        app.suggester, self.calls = provider(reply(GOOD) if response is None else response)
        return app

    def test_suggestions_replace_home_pool_but_never_speak(self):
        app = self.make_app()
        state = app.suggest(dict(session_id=app.session_id, heard_text="Do you want some tea?"))
        self.assertEqual(state["suggestions_provider"], "ollama")
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
        self.assertIn("Yes, tea would be lovely.", self.calls[-1][2]["messages"][1]["content"])
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
            self.assertEqual(state["suggestions_provider"], "ollama")
            self.assertEqual(state["heard"], "Do you want some tea?")
            app.suggester.model = ""
            with self.assertRaises(HTTPError) as error:
                post(dict(session_id=app.session_id, heard_text="hi"))
            error.exception.close()
            self.assertEqual(error.exception.code, 503)
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == "__main__":
    unittest.main()
