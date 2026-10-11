import base64
import json
import os
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app import Application, make_handler
from backend.suggestions import (REPLY_KINDS, OllamaSuggestions, SuggestionBusy, SuggestionUnavailable,
                                 clean_line, clean_suggestions, format_timing, echoes_incoming, basic_offer_replies)


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


def provider(response=None, error=None, model="qwen3:1.7b", mode="single"):
    calls = []

    def transport(url, headers, body, timeout):
        calls.append((url, headers, body, timeout))
        if error:
            raise error
        return response

    with patch("backend.suggestions.load_env"), patch.dict(os.environ, {"OLLAMA_URL": "http://127.0.0.1:11434"}):
        suggester = OllamaSuggestions(transport=transport, mode=mode)
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
        self.assertEqual(cleaned[1]["label"], "Thanks a")
        self.assertTrue(cleaned[0]["id"].startswith("ai-"))

    def test_labels_come_from_reply_text_not_model(self):
        items = [dict(label="REPLY-1", text="Can you call her for me, please?"),
                 dict(label="Agree", text="Yes, please."),
                 dict(text="Unbelievably wonderful news!"), dict(text="Congratulations, everyone!")]
        self.assertEqual([item["label"] for item in clean_suggestions(items)],
                         ["Can you", "Yes", "Unbelievably", "Congrats"])

    def test_meaning_labels_are_short_without_shortening_spoken_text(self):
        sentence = "Could you stay with me a little longer, please?"
        items = clean_suggestions([dict(label="Stay", text=sentence),
                                   dict(label="An overly long model label", text="Thank you for coming to see me.")])
        self.assertEqual(items[0]["label"], "Stay")
        self.assertEqual(items[0]["text"], sentence)
        self.assertTrue(all(len(x["label"].split()) <= 2 for x in items))

    def test_misleading_answer_label_and_first_person_echo_are_rejected(self):
        item = clean_suggestions([dict(label="Later", text="What did you study for?")])[0]
        self.assertNotEqual(item["label"], "Later")
        self.assertTrue(echoes_incoming("I passed my exam today too.", "I passed my exam today."))

    def test_limits_to_five_and_tolerates_non_lists(self):
        many = [dict(label=str(i), text=f"Reply number {i}.") for i in range(9)]
        self.assertEqual(len(clean_suggestions(many)), 5)
        self.assertEqual(clean_suggestions(None), [])


class ProviderTests(unittest.TestCase):
    def test_simple_offer_has_short_labels_and_complete_replies_in_both_modes(self):
        for mode in ("single", "parallel"):
            with self.subTest(mode=mode):
                suggester, calls = provider(error=URLError("not needed"), mode=mode)
                result = suggester.suggest(heard_text="Do you want to eat?", notes="Old unrelated news.",
                                          avoid=["Yes, I would like to eat, thank you."])
                self.assertEqual([x["label"] for x in result.suggestions], ["Yes", "No", "Later"])
                self.assertEqual(result.suggestions[0]["text"], "Yes, I would like to eat, thank you.")
                self.assertIn("eat", result.suggestions[2]["text"])
                self.assertEqual((result.provider, calls), ("quick-replies", []))
                self.assertEqual(result.heard, "Do you want to eat?")
        for text in ("Do you want to eat or go out?", "Do you not want to eat?",
                     "Does he want to eat?", "Why do you want to eat?", "Do you want to rest food?"):
            self.assertEqual(basic_offer_replies(text), [])
        self.assertEqual(len(basic_offer_replies("Would you like to drink some water now?")), 3)

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
        self.assertEqual(result.suggestions[0]["label"], "Yes")  # From the reply, not the model.
        self.assertIn("label", body["messages"][0]["content"])

    def test_current_turn_is_last_and_prior_suggestions_are_not_prompt_topics(self):
        suggester, calls = provider(reply(GOOD))
        suggester.suggest(contact=dict(name='AJ'), recent=['Earlier confirmed reply.'],
                          avoid=['Old swimming suggestion.'], heard_text='Would you like water?',
                          notes='Old exchange: Are you coming swimming? I like casual wording.')
        body=calls[0][2]
        system=body['messages'][0]['content'];context=body['messages'][1]['content']
        self.assertIn("not a rewrite",system)
        self.assertNotIn('Old swimming suggestion.',context)
        self.assertGreater(context.index('CURRENT INCOMING TURN'),context.index('</notes>'))
        self.assertTrue(context.endswith('do not rewrite it or answer background examples.'))
        self.assertIn('"Would you like water?"',context)

    def test_exact_incoming_echo_is_dropped_in_both_modes(self):
        for mode in ('single','parallel'):
            content=reply({'suggestions':[{'text':'Would you like water?'},{'text':'Yes please.'}]}) if mode=='single' else reply('Would you like water?')
            suggester,_=provider(content,mode=mode)
            if mode=='single':
                result=suggester.suggest(heard_text='Would you like water?')
                self.assertEqual([s['text'] for s in result.suggestions],['Yes please.'])
                self.assertEqual(result.timing['echoes_dropped'],1)
            else:
                with self.assertRaises(SuggestionUnavailable):suggester.suggest(heard_text='Would you like water?')
        self.assertFalse(echoes_incoming('Yes.','Yes'))
        self.assertFalse(echoes_incoming('What kind of water?','Would you like water?'))

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


class ParallelTests(unittest.TestCase):
    LINES = {"yes or agreement": "Yes, tea would be lovely.", "polite no": "1. No thank you, I am fine.",
             "follow-up question": '"What kind of tea is it?"', "warm or caring": "That is so kind of you.\nExtra line.",
             "simple need": "Could I have some water too?"}

    def parallel(self, fail=()):
        calls = []

        def transport(url, headers, body, timeout):
            calls.append(body)
            ask = body["messages"][1]["content"].rsplit("\n", 1)[-1]
            key = next(key for key in self.LINES if key in ask)
            if key in fail:
                raise URLError("down")
            return {"message": {"content": self.LINES[key]}, "eval_count": 12, "eval_duration": 400_000_000,
                    "prompt_eval_count": 90, "prompt_eval_duration": 50_000_000, "load_duration": 1_000_000}

        suggester = OllamaSuggestions(transport=transport, mode="parallel")
        suggester.model = "qwen3:1.7b"
        return suggester, calls

    def test_one_short_plain_request_per_reply_kind(self):
        suggester, calls = self.parallel()
        result = suggester.suggest(contact=dict(name="Alex", relationship="Family"), heard_text="Tea?")
        self.assertEqual(len(calls), len(REPLY_KINDS))
        for body in calls:
            self.assertEqual(body["format"], "json")
            self.assertEqual((body["stream"], body["think"]), (False, False))
            self.assertLessEqual(body["options"]["num_predict"], 120)
            self.assertIn('"Tea?"', body["messages"][1]["content"])
        prefixes = {body["messages"][1]["content"].rsplit("\n", 1)[0] for body in calls}
        self.assertEqual(len(prefixes), 1)  # Shared prefix; only the reply kind differs.
        self.assertEqual([item["text"] for item in result.suggestions],
                         ["Yes, tea would be lovely.", "No thank you, I am fine.", "What kind of tea is it?",
                          "That is so kind of you.", "Could I have some water too?"])
        self.assertEqual((result.timing["mode"], result.timing["requests"], result.timing["gen_tokens"],
                          result.timing["gen_ms"]), ("parallel", 5, 60, 400))
        self.assertIn("parallel x5", format_timing(result.timing))

    def test_parallel_json_keeps_meaning_label_and_full_warm_sentence(self):
        suggester, _ = provider(mode="parallel")
        lines = [dict(label="Stay", text="Could you stay with me a little longer, please?"),
                 dict(label="Yes", text="Yes, I would love that, thank you."),
                 dict(label="Later", text="Later, please. I need a little time.")]
        counter = iter(lines + lines[:2])
        lock = threading.Lock()
        def transport(*args):
            with lock:
                item = next(counter)
            return reply(item)
        suggester.transport = transport
        result = suggester.suggest(heard_text="Can I keep you company?")
        stay = next(x for x in result.suggestions if x["label"] == "Stay")
        self.assertEqual(stay["text"], lines[0]["text"])
        self.assertTrue(all(len(x["label"].split()) <= 2 for x in result.suggestions))

    def test_partial_failure_keeps_the_rest_and_total_failure_raises(self):
        suggester, _ = self.parallel(fail=("polite no", "warm or caring"))
        self.assertEqual(len(suggester.suggest(heard_text="Tea?").suggestions), 3)
        suggester, _ = self.parallel(fail=tuple(self.LINES))
        with self.assertRaises(SuggestionUnavailable):
            suggester.suggest(heard_text="Tea?")

    def test_clean_line_and_mode_validation(self):
        self.assertEqual(clean_line("\n- “Sure thing.”\nmore"), "Sure thing.")
        self.assertEqual(clean_line("2) Okay."), "Okay.")
        self.assertEqual(clean_line("   "), "")
        with self.assertRaises(ValueError):
            OllamaSuggestions(mode="fastest")

    def test_single_mode_reports_timing_and_warm_is_best_effort(self):
        body = dict(reply(GOOD), eval_count=150, eval_duration=5_000_000_000, load_duration=0)
        suggester, calls = provider(body)
        self.assertEqual(suggester.suggest(heard_text="Tea?").timing["gen_tokens"], 150)
        self.assertTrue(suggester.warm())
        self.assertEqual(calls[-1][2]["options"], dict(num_predict=1))
        self.assertFalse(provider(error=URLError("down"))[0].warm())
        self.assertFalse(provider(model="")[0].warm())


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

    def test_offer_wheel_pages_and_full_sentence_confirmation(self):
        app = self.make_app()
        app.ring.cardinal_layout = True
        state = app.suggest(dict(session_id=app.session_id, heard_text="Do you want to eat?"))
        self.assertEqual([state["slots"][i]["label"] for i in (6, 2, 0, 4)],
                         ["Yes", "No", "More", "Back"])
        self.assertEqual(state["selection_id"], 0)
        app.ring.action("focus", value=6)
        app.ring.action("select")
        self.assertEqual(app.ring.confirmed, "Yes, I would like to eat, thank you.")
        app.ring.action("focus", value=0)
        app.ring.action("select")
        self.assertEqual(app.ring.slots()[6]["label"], "Later")
        self.assertFalse(app.ring.slots()[2]["enabled"])
        app.ring.action("focus", value=6)
        app.ring.action("select")
        self.assertEqual(app.ring.confirmed, "Later, please. I would like to eat in a little while.")

    def test_default_choices_restore_home_and_cancel_pending_choice_without_selection(self):
        app = self.make_app()
        app.ring.cardinal_layout = True
        app.suggest(dict(session_id=app.session_id, heard_text="Tea?"))
        app.ring.action("focus", value=6)
        app.eog_confirmation.focus(app.ring, 1000)
        self.assertIsNotNone(app.eog_confirmation.target)
        app.ring.screen = "needs"
        app.ring.pages = {"home": 2, "needs": 1}
        app.ring.confirm("Earlier confirmed sentence.")
        previous = app.ring.snapshot()
        state = app.command(dict(action="default_choices", event_id="restore-defaults"))
        self.assertEqual((state["screen"], state["page"], state["selected"]), ("home", 0, 6))
        self.assertEqual([state["slots"][i]["label"] for i in (6, 2, 0, 4)],
                         ["Hello", "Goodbye", "More", "Back"])
        self.assertEqual([p["label"] for p in app.ring.suggested], ["Hello", "Goodbye", "Yes", "No", "Help"])
        self.assertEqual(state["heard"], "")
        self.assertEqual(state["suggestions_provider"], "preset")
        self.assertIsNone(app.eog_confirmation.target)
        self.assertEqual((state["selection_id"], state["confirmed"], state["history"]),
                         (previous["selection_id"], previous["confirmed"], previous["history"]))

    def test_speech_suggestions_take_precedence_over_defaults_during_generation(self):
        app = self.make_app()
        def restore_during_generation(*args):
            app.command(dict(action="default_choices", event_id="restore-inflight"))
            return reply(GOOD)
        app.suggester.transport = restore_during_generation
        state = app.suggest(dict(session_id=app.session_id, heard_text="Tea?"))
        self.assertEqual(state["slots"][0]["text"], "Yes, tea would be lovely.")
        self.assertEqual(state["suggestions_provider"], "ollama")
        self.assertEqual(state["selection_id"], 0)

    def test_audio_replies_replace_defaults_and_navigation_does_not_discard_them(self):
        app = self.make_app()
        app.ring.cardinal_layout = True
        app.command(dict(action="default_choices", event_id="defaults-before-listening"))
        app.transcriber.url = "http://jetson:8000"
        app.transcriber.transport = lambda *args: dict(text="Do you want some tea?")
        def navigate_during_generation(*args):
            app.ring.action("focus", value=2)
            app.eog_confirmation.focus(app.ring, 1000)
            return reply(GOOD)
        app.suggester.transport = navigate_during_generation
        state = app.suggest(dict(session_id=app.session_id, mime_type="audio/webm",
                                 audio_b64=base64.b64encode(b"test audio").decode()))
        self.assertEqual(state["suggestions_provider"], "ollama")
        self.assertEqual((state["screen"], state["selected"]), ("home", 6))
        self.assertEqual(state["slots"][6]["text"], "Yes, tea would be lovely.")
        self.assertEqual(state["heard"], "Do you want some tea?")
        self.assertIsNone(app.eog_confirmation.target)
        self.assertEqual((state["selection_id"], state["confirmed"]), (0, ""))

    def test_contact_change_during_asr_does_not_attribute_audio_to_new_partner(self):
        app = self.make_app()
        app.transcriber.url = "http://jetson:8000"
        def switch_partner(*args):
            app.command(dict(action="contact", value=app.ring.config["contacts"][1]["id"], event_id="switch-during-asr"))
            return dict(text="Tea?")
        app.transcriber.transport = switch_partner
        with self.assertRaisesRegex(SuggestionUnavailable, "Conversation changed"):
            app.suggest(dict(session_id=app.session_id, mime_type="audio/webm",
                             audio_b64=base64.b64encode(b"test audio").decode()))
        self.assertEqual(self.calls, [])
        self.assertEqual(app.state()["heard"], "")

    def test_new_replies_return_from_secondary_screen_to_home(self):
        app = self.make_app()
        app.ring.screen = "needs"
        state = app.suggest(dict(session_id=app.session_id, heard_text="Tea?"))
        self.assertEqual(state["screen"], "home")
        self.assertEqual(state["slots"][0]["text"], "Yes, tea would be lovely.")

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
        self.assertNotIn("Yes, tea would be lovely.", self.calls[-1][2]["messages"][1]["content"]) # Old choices must not anchor the new topic.
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
